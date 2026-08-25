from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import streamlit as st
from sqlalchemy import update

from nl_json_translator.config import config_from_env, load_env_file
from nl_json_translator.deepseek_client import DeepSeekClient
from nl_json_translator.domain.enums import OrderStatus
from nl_json_translator.domain.schemas import TransportIntentDraft
from nl_json_translator.fleet_renderer import render_fleet_svg
from nl_json_translator.infrastructure.database import Database, default_database_url
from nl_json_translator.infrastructure.demo_map import DEMO_VEHICLES
from nl_json_translator.infrastructure.orm_models import VehicleRecord
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.map_executor import execute_command, pretty_json
from nl_json_translator.prompts import build_messages
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.repositories.vehicles import VehicleRepository
from nl_json_translator.services.dispatch_service import DispatchResult, DispatchService
from nl_json_translator.services.fleet_simulation_service import (
    FleetRuntimeFrame,
    FleetSimulation,
    FleetSimulationService,
)
from nl_json_translator.services.fleet_view_service import FleetViewService
from nl_json_translator.services.location_resolver import LocationResolution
from nl_json_translator.services.order_service import OrderService
from nl_json_translator.translator import Translator


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_REQUEST = "从 A 取 3 箱零件送到 B"
FRAME_DELAY_SECONDS = 0.12


def main() -> None:
    st.set_page_config(page_title="场内多车调度 Demo", layout="wide")
    load_env_file(ROOT_DIR / ".env")
    _init_state()
    database_url = default_database_url()
    seed_demo_data(database_url)
    location_names = _location_names(database_url)

    st.title("场内多车货物运输调度 Demo")
    with st.sidebar:
        model = st.selectbox("模型", ["deepseek-v4-pro", "deepseek-v4-flash"], index=0)
        start_point = st.selectbox("未分配时的路径预览起点", location_names, index=0)
        show_prompt = st.toggle("显示 Prompt", value=False)
        st.divider()
        st.caption("自然语言 → 订单 → 中央调度 → Mission → 多车计划路线")
        if st.button("清空结果", width="stretch"):
            st.session_state.last_result = None
            st.session_state.last_frame_index = 0
            st.rerun()

    request_text = st.text_area(
        "自然语言运输请求",
        value=st.session_state.get("request_text", DEFAULT_REQUEST),
        height=90,
    )
    st.session_state.request_text = request_text
    col_run, col_dispatch, col_replay = st.columns(3)
    run_clicked = col_run.button("创建订单并播放", type="primary", width="stretch")
    dispatch_clicked = col_dispatch.button("调度并播放全部任务", width="stretch")
    replay_clicked = col_replay.button(
        "重播轨迹",
        width="stretch",
        disabled=not bool(
            st.session_state.last_result
            and (
                st.session_state.last_result.get("fleet_simulation")
                or st.session_state.last_result.get("frames")
            )
        ),
    )

    if run_clicked:
        with st.spinner("Pipeline running..."):
            st.session_state.last_result = run_pipeline(
                request_text=request_text,
                model=model,
                start_point=start_point,
                database_url=database_url,
            )
            st.session_state.last_frame_index = 0
            st.session_state.autoplay = True
    if dispatch_clicked:
        st.session_state.last_result = run_fleet_dispatch(database_url)
        st.session_state.last_frame_index = 0
        st.session_state.autoplay = True
    if replay_clicked:
        st.session_state.last_frame_index = 0
        st.session_state.autoplay = True
    notice = st.session_state.pop("dispatch_notice", None)
    if notice:
        st.success(notice)

    render_fleet_dashboard(database_url)

    if st.session_state.last_result:
        render_result(
            st.session_state.last_result,
            show_prompt,
            autoplay=st.session_state.get("autoplay", False),
            database_url=database_url,
        )
        st.session_state.autoplay = False


def _init_state() -> None:
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("last_frame_index", 0)
    st.session_state.setdefault("request_text", DEFAULT_REQUEST)
    st.session_state.setdefault("autoplay", False)
    st.session_state.setdefault("dispatch_notice", None)


def _location_names(database_url: str) -> list[str]:
    database = Database(database_url)
    try:
        with database.session() as session:
            names = sorted(location.name for location in MapRepository(session).load().locations.values())
        return names or ["A"]
    finally:
        database.dispose()


def run_pipeline(
    *, request_text: str, model: str, start_point: str, database_url: str
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "natural_language": request_text,
        "model": model,
        "start_point": start_point,
        "translation": None,
        "validation": {"ok": False},
        "order": None,
        "dispatch": None,
        "internal_mission_command": None,
        "execution": None,
        "frames": [],
        "fleet_simulation": None,
        "simulation_finalized": False,
        "prompt_messages": build_messages(request_text) if request_text.strip() else [],
        "logs": [],
    }
    database: Optional[Database] = None
    try:
        config = config_from_env(model=model)
        translated = Translator(DeepSeekClient(config)).translate(request_text)
        draft = TransportIntentDraft.model_validate(translated.intent)
        result["translation"] = {
            "source": "deepseek",
            "intent": draft.model_dump(mode="json"),
            "raw_response": translated.raw_response,
            "attempts": translated.attempts,
        }
        result["validation"] = {"ok": True, "message": "运输意图 Schema 校验通过。"}
        result["logs"].append(f"Transport intent extracted in {translated.attempts} attempt(s).")

        database = Database(database_url)
        with database.session() as session:
            order_result = OrderService(session).create_from_intent(
                draft, idempotency_key=f"ui-{uuid4().hex}"
            )
            result["order"] = {
                "id": order_result.order_id,
                "status": order_result.status.value,
                "formal_order": (
                    order_result.formal_order.model_dump(mode="json")
                    if order_result.formal_order
                    else None
                ),
                "pickup_resolution": _resolution_dict(order_result.pickup_resolution),
                "dropoff_resolution": _resolution_dict(order_result.dropoff_resolution),
            }
            result["logs"].append(
                f"Order {order_result.order_id} persisted as {order_result.status.value}."
            )
            if not order_result.formal_order:
                result["logs"].append("Location confirmation is required before execution.")
                return result

            formal_order = order_result.formal_order
            _refresh_demo_telemetry(session)
            dispatch_result = DispatchService(session).dispatch_order(order_result.order_id)
            result["dispatch"] = _dispatch_dict(dispatch_result)
            if not dispatch_result.assigned:
                result["logs"].append(
                    "No eligible idle vehicle is currently available; order remains RESOLVED."
                )
                _attach_active_fleet_simulation(result, session)
                return result
            result["order"]["status"] = "ASSIGNED"
            result["logs"].append(
                f"Mission {dispatch_result.mission.id} assigned to "
                f"{dispatch_result.selected_vehicle_id} at cost {dispatch_result.selected_cost}."
            )
            internal_command = {
                "action": "sequence",
                "params": [
                    {
                        "action": "go_to_goal",
                        "params": {
                            "location": {
                                "type": "str",
                                "value": formal_order.pickup_location_id,
                            }
                        },
                    },
                    {
                        "action": "go_to_goal",
                        "params": {
                            "location": {
                                "type": "str",
                                "value": formal_order.dropoff_location_id,
                            }
                        },
                    },
                ],
            }
            repository = MapRepository(session)
            selected_vehicle = VehicleRepository(session).get(
                dispatch_result.selected_vehicle_id
            )
            execution_start = (
                selected_vehicle.current_node_id if selected_vehicle else start_point
            )
            result["internal_mission_command"] = internal_command
            result["execution"] = execute_command(
                internal_command, repository=repository, start=execution_start
            )
            _attach_active_fleet_simulation(result, session)
            result["logs"].append(
                f"Fleet simulation starts from persisted vehicle node {execution_start}."
            )
    except Exception as exc:
        result["validation"] = {"ok": False, "message": str(exc)}
        result["logs"].append(f"Pipeline failed: {exc}")
    finally:
        if database:
            database.dispose()
    return result


def _resolution_dict(resolution: Optional[LocationResolution]) -> Optional[dict[str, Any]]:
    if not resolution:
        return None
    return {
        "query": resolution.query,
        "status": resolution.status.value,
        "location_id": resolution.location_id,
        "candidates": [candidate.__dict__ for candidate in resolution.candidates],
    }


def _dispatch_dict(result: DispatchResult) -> dict[str, Any]:
    return {
        "assigned": result.assigned,
        "order_id": result.order_id,
        "mission_id": result.mission.id if result.mission else None,
        "selected_vehicle_id": result.selected_vehicle_id,
        "selected_cost": result.selected_cost,
        "candidates": [
            {
                "vehicle_id": candidate.vehicle_id,
                "vehicle_name": candidate.vehicle_name,
                "eligible": candidate.eligible,
                "cost": candidate.cost,
                "reasons": list(candidate.reasons),
            }
            for candidate in result.candidates
        ],
        "steps": [
            {
                "sequence": step.sequence_no,
                "type": step.step_type.value,
                "status": step.status.value,
                "start_node_id": step.start_node_id,
                "end_node_id": step.end_node_id,
            }
            for step in (result.mission.steps if result.mission else ())
        ],
    }


def run_fleet_dispatch(database_url: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "natural_language": None,
        "model": "deterministic-dispatch",
        "translation": None,
        "validation": {"ok": True, "message": "待处理订单已进入确定性调度。"},
        "order": None,
        "dispatch": None,
        "internal_mission_command": None,
        "execution": None,
        "frames": [],
        "fleet_simulation": None,
        "simulation_finalized": False,
        "prompt_messages": [],
        "logs": [],
    }
    database = Database(database_url)
    try:
        with database.session() as session:
            _refresh_demo_telemetry(session)
            results = DispatchService(session).dispatch_all_ready()
            assigned = sum(item.assigned for item in results)
            waiting = len(results) - assigned
            result["dispatch"] = {
                "assigned": assigned > 0,
                "assigned_count": assigned,
                "waiting_count": waiting,
                "results": [_dispatch_dict(item) for item in results],
            }
            result["logs"].append(
                f"Dispatch assigned {assigned} order(s); {waiting} order(s) remain waiting."
            )
            _attach_active_fleet_simulation(result, session)
            if not result["fleet_simulation"].mission_ids:
                result["validation"] = {
                    "ok": False,
                    "message": "当前没有可播放的活动 Mission。",
                }
        return result
    finally:
        database.dispose()


def _attach_active_fleet_simulation(result: dict[str, Any], session: Any) -> None:
    map_data = MapRepository(session).load()
    snapshot = FleetViewService(session).snapshot()
    result["fleet_simulation"] = FleetSimulationService(session).build(
        map_data,
        snapshot,
    )


def _complete_fleet_simulation(database_url: str, simulation: FleetSimulation) -> int:
    database = Database(database_url)
    try:
        with database.session() as session:
            return FleetSimulationService(session).complete(simulation)
    finally:
        database.dispose()


def _refresh_demo_telemetry(session: Any) -> None:
    """The in-process demo treats every UI interaction as fresh simulated telemetry."""

    vehicle_ids = [definition["id"] for definition in DEMO_VEHICLES]
    session.execute(
        update(VehicleRecord)
        .where(VehicleRecord.id.in_(vehicle_ids))
        .values(telemetry_updated_at=datetime.now(timezone.utc))
    )


def render_fleet_dashboard(database_url: str) -> None:
    database = Database(database_url)
    try:
        with database.session() as session:
            snapshot = FleetViewService(session).snapshot()
            map_data = MapRepository(session).load()
    finally:
        database.dispose()

    st.subheader("多车调度总览")
    assigned_orders = snapshot.order_counts.get(OrderStatus.ASSIGNED, 0)
    resolved_orders = snapshot.order_counts.get(OrderStatus.RESOLVED, 0)
    metric_cols = st.columns(4)
    metric_cols[0].metric("车辆", len(snapshot.vehicles))
    metric_cols[1].metric("空闲", snapshot.idle_vehicle_count)
    metric_cols[2].metric("活动 Mission", len(snapshot.active_missions))
    metric_cols[3].metric("待分配 / 已分配", f"{resolved_orders} / {assigned_orders}")

    labels = {vehicle.id: f"{vehicle.name} · {vehicle.status.value}" for vehicle in snapshot.vehicles}
    selected = st.selectbox(
        "聚焦车辆",
        [""] + list(labels),
        format_func=lambda value: "全部车辆" if not value else labels[value],
        key="fleet_selected_vehicle",
    )
    map_column, fleet_column = st.columns([2.15, 1])
    with map_column:
        st.image(
            render_fleet_svg(map_data, snapshot, selected_vehicle_id=selected or None),
            width="stretch",
        )
        st.caption("虚线表示已分配 Mission 的计划路线；聚焦车辆后会突出其路线。")
    with fleet_column:
        st.dataframe(
            [
                {
                    "车辆": vehicle.name,
                    "状态": vehicle.status.value,
                    "电量": f"{vehicle.battery_level:.0f}%",
                    "节点": vehicle.node_id,
                    "订单": vehicle.order_id or "—",
                }
                for vehicle in snapshot.vehicles
            ],
            width="stretch",
            hide_index=True,
        )

    mission_tab, event_tab = st.tabs(["Mission 与步骤", "最近调度事件"])
    with mission_tab:
        mission_rows = [
            {
                "Mission": mission.id,
                "订单": mission.order_id,
                "车辆": mission.vehicle_id,
                "状态": mission.status.value,
                "步骤": " → ".join(step.step_type.value for step in mission.steps),
            }
            for mission in snapshot.active_missions
        ]
        if mission_rows:
            st.dataframe(mission_rows, width="stretch", hide_index=True)
        else:
            st.info("当前没有活动 Mission。")
    with event_tab:
        event_rows = [
            {
                "时间": event.occurred_at.isoformat(timespec="seconds"),
                "事件": event.event_type,
                "车辆": event.vehicle_id or "—",
                "订单": event.order_id or "—",
                "Mission": event.mission_id or "—",
            }
            for event in snapshot.recent_events
        ]
        if event_rows:
            st.dataframe(event_rows, width="stretch", hide_index=True)
        else:
            st.info("尚无调度事件。")


def render_result(
    result: dict[str, Any],
    show_prompt: bool,
    *,
    autoplay: bool,
    database_url: str,
) -> None:
    translation = result.get("translation") or {}
    validation = result.get("validation") or {}
    order = result.get("order") or {}
    dispatch = result.get("dispatch") or {}
    execution = result.get("execution") or {}
    frames = result.get("frames") or []
    fleet_simulation = result.get("fleet_simulation")
    st.subheader("运行结果")
    metric_cols = st.columns(4)
    metric_cols[0].metric("意图来源", translation.get("source", "none"))
    metric_cols[1].metric("意图校验", "通过" if validation.get("ok") else "失败")
    metric_cols[2].metric("订单状态", order.get("status", "未创建"))
    metric_cols[3].metric("调度车辆", dispatch.get("selected_vehicle_id") or "未分配")
    if validation.get("ok"):
        st.success(validation.get("message"))
    else:
        st.error(validation.get("message"))
    if order.get("status") == "NEEDS_REVIEW":
        st.warning("地点存在歧义，订单已进入 NEEDS_REVIEW，未执行路径。")
    if (
        dispatch
        and not dispatch.get("assigned")
        and not (fleet_simulation and fleet_simulation.mission_ids)
    ):
        st.warning("当前没有满足硬约束的空闲车辆，订单保持 RESOLVED。")
    playback_completed = False
    if fleet_simulation and fleet_simulation.mission_ids:
        playback_completed = render_fleet_runtime(
            fleet_simulation,
            database_url=database_url,
            autoplay=autoplay,
        )
    else:
        render_runtime(frames, autoplay=autoplay)

    if playback_completed and not result.get("simulation_finalized"):
        completed_count = _complete_fleet_simulation(database_url, fleet_simulation)
        result["simulation_finalized"] = True
        if result.get("order") and completed_count:
            result["order"]["status"] = "DELIVERED"
        result["logs"].append(
            f"Fleet playback completed and persisted {completed_count} Mission(s)."
        )
        st.session_state.autoplay = False
        st.rerun()

    tab_order, tab_dispatch, tab_intent, tab_internal, tab_prompt, tab_log = st.tabs(
        ["订单", "调度决策", "运输意图", "内部执行", "Prompt", "日志"]
    )
    with tab_order:
        st.json(order, expanded=True)
    with tab_dispatch:
        if dispatch:
            st.json(dispatch, expanded=True)
        else:
            st.write("该订单尚未进入调度。")
    with tab_intent:
        intent = translation.get("intent")
        if intent:
            st.code(pretty_json(intent), language="json")
        if translation.get("raw_response"):
            with st.expander("Raw model response", expanded=False):
                st.code(translation["raw_response"], language="json")
    with tab_internal:
        if result.get("internal_mission_command"):
            st.code(pretty_json(result["internal_mission_command"]), language="json")
        if execution:
            st.dataframe(execution["timeline"], width="stretch", hide_index=True)
    with tab_prompt:
        if show_prompt:
            st.json(result.get("prompt_messages", []), expanded=False)
        else:
            st.write("在侧边栏启用“显示 Prompt”以查看。")
    with tab_log:
        st.json(
            {
                key: value
                for key, value in result.items()
                if key != "fleet_simulation"
            },
            expanded=False,
        )


def render_fleet_runtime(
    simulation: FleetSimulation,
    *,
    database_url: str,
    autoplay: bool,
) -> bool:
    st.subheader("动态多车取货与送货过程")
    database = Database(database_url)
    try:
        with database.session() as session:
            map_data = MapRepository(session).load()
    finally:
        database.dispose()

    labels = {
        vehicle.id: vehicle.name
        for vehicle in simulation.snapshot.vehicles
        if vehicle.mission_id in simulation.mission_ids
    }
    selected = st.selectbox(
        "动态过程聚焦车辆",
        [""] + list(labels),
        format_func=lambda value: "全部执行车辆" if not value else labels[value],
        key="runtime_selected_vehicle",
    )
    map_slot, table_slot, caption_slot, progress_slot = (
        st.empty(),
        st.empty(),
        st.empty(),
        st.empty(),
    )
    frames = simulation.frames
    if autoplay:
        for index, frame in enumerate(frames):
            show_fleet_runtime_frame(
                map_slot,
                table_slot,
                caption_slot,
                progress_slot,
                map_data,
                simulation,
                frame,
                selected_vehicle_id=selected or None,
            )
            st.session_state.last_frame_index = index
            time.sleep(FRAME_DELAY_SECONDS)
        return True

    max_index = len(frames) - 1
    selected_index = st.slider(
        "多车执行时间片",
        min_value=0,
        max_value=max_index,
        value=min(st.session_state.last_frame_index, max_index),
        disabled=max_index == 0,
        key="fleet_runtime_slider",
    )
    st.session_state.last_frame_index = selected_index
    show_fleet_runtime_frame(
        map_slot,
        table_slot,
        caption_slot,
        progress_slot,
        map_data,
        simulation,
        frames[selected_index],
        selected_vehicle_id=selected or None,
    )
    return False


def show_fleet_runtime_frame(
    map_slot: Any,
    table_slot: Any,
    caption_slot: Any,
    progress_slot: Any,
    map_data: Any,
    simulation: FleetSimulation,
    frame: FleetRuntimeFrame,
    *,
    selected_vehicle_id: Optional[str],
) -> None:
    map_slot.image(
        render_fleet_svg(
            map_data,
            simulation.snapshot,
            selected_vehicle_id=selected_vehicle_id,
            runtime_frame=frame,
        ),
        width="stretch",
    )
    active_states = [state for state in frame.vehicles if state.mission_id]
    table_slot.dataframe(
        [
            {
                "车辆": state.vehicle_id,
                "阶段": state.phase,
                "位置": state.node_id,
                "货物": state.cargo_name or "—",
                "载货": "是" if state.carrying_cargo else "否",
                "订单": state.order_id,
            }
            for state in active_states
        ],
        width="stretch",
        hide_index=True,
    )
    caption_slot.caption(
        f"时间片 {frame.index + 1}/{len(simulation.frames)} ｜ "
        "实线为已行驶路线，虚线为剩余路线，黄色“货”标记表示车辆已装货。"
    )
    progress_slot.progress((frame.index + 1) / len(simulation.frames))


def render_runtime(frames: list[dict[str, Any]], *, autoplay: bool) -> None:
    st.subheader("数据库地图上的单车取送轨迹")
    if not frames:
        st.info("订单解析成功且无需人工确认后，将在此显示轨迹。")
        return
    frame_slot, status_slot, progress_slot = st.empty(), st.empty(), st.empty()
    if autoplay:
        for index, frame in enumerate(frames):
            show_runtime_frame(frame_slot, status_slot, progress_slot, frame, index, len(frames))
            time.sleep(FRAME_DELAY_SECONDS)
        st.session_state.last_frame_index = len(frames) - 1
        return
    max_index = len(frames) - 1
    selected_index = st.slider(
        "运行进度",
        min_value=0,
        max_value=max_index,
        value=min(st.session_state.last_frame_index, max_index),
        disabled=max_index == 0,
    )
    st.session_state.last_frame_index = selected_index
    show_runtime_frame(frame_slot, status_slot, progress_slot, frames[selected_index], selected_index, len(frames))


def show_runtime_frame(
    frame_slot: Any,
    status_slot: Any,
    progress_slot: Any,
    frame: dict[str, Any],
    index: int,
    total: int,
) -> None:
    pose = frame.get("pose") or {}
    frame_slot.image(frame["svg"], width="stretch")
    status_slot.caption(
        f"Frame {index + 1}/{total} | Step {frame.get('step')} | {frame.get('action')} | "
        f"{frame.get('detail')} | Pose ({pose.get('x')}, {pose.get('y')}), "
        f"heading {pose.get('heading')}°"
    )
    progress_slot.progress((index + 1) / total)


if __name__ == "__main__":
    main()
