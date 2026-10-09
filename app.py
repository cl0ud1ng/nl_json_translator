from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import streamlit as st
from sqlalchemy import update

from nl_json_translator.agent_flow_renderer import render_agent_flow_svg
from nl_json_translator.agents import AgentRuntime, DispatcherAgent
from nl_json_translator.config import config_from_env, load_env_file
from nl_json_translator.deepseek_client import DeepSeekClient
from nl_json_translator.domain.enums import OrderStatus
from nl_json_translator.domain.schemas import TransportRequestDraft
from nl_json_translator.fleet_renderer import (
    render_fleet_svg,
    retain_completed_route_states,
)
from nl_json_translator.infrastructure.database import Database, default_database_url
from nl_json_translator.infrastructure.demo_map import DEMO_VEHICLES
from nl_json_translator.infrastructure.orm_models import TransportOrderRecord, VehicleRecord
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.map_executor import pretty_json
from nl_json_translator.prompts import build_messages
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.services.demo_scenario_service import DemoScenarioService
from nl_json_translator.services.dispatch_service import DispatchResult, DispatchService
from nl_json_translator.services.fleet_simulation_service import (
    FleetRuntimeFrame,
    FleetSimulation,
    FleetSimulationService,
)
from nl_json_translator.services.fleet_view_service import FleetSnapshot, FleetViewService
from nl_json_translator.services.location_resolver import LocationResolution
from nl_json_translator.translator import Translator


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_REQUEST = (
    "创建两张独立运输订单并并发调度：1）从 A 取 1 箱零件箱 A（25kg）送到 B；"
    "2）从 C 取 1 箱零件箱 B（30kg）送到 lab。必须分配给 2 辆不同的车，"
    "每辆车只执行一张订单；整体恰好包含 2 个"
    "不同取货点和 2 个不同目标点。"
)
FRAME_DELAY_SECONDS = 0.12


def main() -> None:
    st.set_page_config(page_title="场内多车调度 Demo", layout="wide")
    load_env_file(ROOT_DIR / ".env")
    _init_state()
    database_url = default_database_url()
    seed_demo_data(database_url)
    st.title("自然语言多车 Agent 调度 Demo")
    with st.sidebar:
        model = st.selectbox("模型", ["deepseek-v4-pro", "deepseek-v4-flash"], index=0)
        show_prompt = st.toggle("显示 Prompt", value=False)
        st.divider()
        st.caption("DeepSeek 批量意图 → DispatcherAgent → N 个 VehicleAgent")
        if st.button("清空结果", width="stretch"):
            st.session_state.last_result = None
            st.session_state.last_frame_index = 0
            st.rerun()

    request_text = st.text_area(
        "自然语言运输请求（支持 1 到 N 张订单）",
        value=st.session_state.get("request_text", DEFAULT_REQUEST),
        height=150,
    )
    st.session_state.request_text = request_text
    reset_before_run = st.checkbox(
        "运行前清理旧任务并恢复 Demo 车辆初始状态", value=True
    )
    col_run, col_reset = st.columns(2)
    run_clicked = col_run.button("调用 DeepSeek 并运行 Agent 链路", type="primary", width="stretch")
    reset_clicked = col_reset.button("重置运行数据", width="stretch")

    if run_clicked:
        with st.spinner("Pipeline running..."):
            st.session_state.last_result = run_pipeline(
                request_text=request_text,
                model=model,
                database_url=database_url,
                reset_before_run=reset_before_run,
            )
            st.session_state.last_frame_index = 0
            st.session_state.autoplay = True
    if reset_clicked:
        st.session_state.dispatch_notice = reset_demo_runtime(database_url)
        st.session_state.last_result = None
        st.session_state.last_frame_index = 0
        st.session_state.pop("fleet_runtime_slider", None)
        st.rerun()
    notice = st.session_state.pop("dispatch_notice", None)
    if notice:
        st.success(notice)

    last_result = st.session_state.last_result or {}
    last_simulation = last_result.get("fleet_simulation")
    render_fleet_dashboard(
        database_url,
        route_snapshot=(last_simulation.snapshot if last_simulation else None),
    )

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


def _location_index(location_names: list[str], preferred: str) -> int:
    try:
        return location_names.index(preferred)
    except ValueError:
        return 0


def run_pipeline(
    *,
    request_text: str,
    model: str,
    database_url: str,
    reset_before_run: bool = False,
    translator: Optional[Translator] = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "natural_language": request_text,
        "model": model,
        "translation": None,
        "validation": {"ok": False},
        "order": None,
        "dispatch": None,
        "internal_mission_command": None,
        "execution": None,
        "frames": [],
        "fleet_simulation": None,
        "simulation_finalized": True,
        "prompt_messages": build_messages(request_text) if request_text.strip() else [],
        "logs": [],
    }
    database: Optional[Database] = None
    try:
        active_translator = translator or Translator(
            DeepSeekClient(config_from_env(model=model))
        )
        translated = active_translator.translate(request_text)
        draft = TransportRequestDraft.model_validate(translated.request)
        result["translation"] = {
            "source": "deepseek",
            "intent": draft.model_dump(mode="json"),
            "raw_response": translated.raw_response,
            "attempts": translated.attempts,
            "response_id": translated.response_id,
            "provider_model": translated.model,
            "finish_reason": translated.finish_reason,
            "usage": translated.usage or {},
        }
        result["logs"].append(
            f"DeepSeek extracted {len(draft.orders)} order(s) in "
            f"{translated.attempts} attempt(s)."
        )

        database = Database(database_url)
        with database.session() as session:
            if reset_before_run:
                reset = DemoScenarioService(session).reset_demo_runtime()
                result["logs"].append(f"Reset runtime before request: {reset}.")
            _refresh_demo_telemetry(session)
            submission = DispatcherAgent(session).submit(
                draft,
                natural_language=request_text,
                provider_response_id=translated.response_id,
                provider_model=translated.model,
                provider_usage=translated.usage,
            )
            result["order"] = {
                "batch_id": submission.batch_id,
                "status": "DISPATCHED" if submission.dispatches else "NEEDS_REVIEW",
                "orders": [
                    {
                        "id": order.order_id,
                        "status": order.status.value,
                        "formal_order": (
                            order.formal_order.model_dump(mode="json")
                            if order.formal_order
                            else None
                        ),
                        "pickup_resolution": _resolution_dict(order.pickup_resolution),
                        "dropoff_resolution": _resolution_dict(order.dropoff_resolution),
                    }
                    for order in submission.orders
                ],
            }
            if not submission.dispatches:
                result["validation"] = {
                    "ok": False,
                    "message": "批量订单包含需要人工确认的地点。",
                }
                return result
            assigned = tuple(item for item in submission.dispatches if item.assigned)
            result["dispatch"] = {
                "assigned": bool(assigned),
                "assigned_count": len(assigned),
                "waiting_count": len(submission.dispatches) - len(assigned),
                "results": [_dispatch_dict(item) for item in submission.dispatches],
            }
            if not assigned:
                result["order"]["status"] = "WAITING"
                result["validation"] = {
                    "ok": False,
                    "message": "当前车队无法满足整批订单的硬约束。",
                }
                return result
            simulation = AgentRuntime(session).run_until_idle()
            result["fleet_simulation"] = simulation
            for order in result["order"]["orders"]:
                record = session.get(TransportOrderRecord, order["id"])
                order["status"] = record.status if record else "UNKNOWN"
            delivered_count = sum(
                order["status"] == "DELIVERED" for order in result["order"]["orders"]
            )
            result["order"]["status"] = (
                "DELIVERED"
                if delivered_count == len(result["order"]["orders"])
                else "PARTIAL"
            )
            result["validation"] = {
                "ok": True,
                "message": (
                    f"DeepSeek 意图已经过 DispatcherAgent 和 "
                    f"{len(assigned)} 个 VehicleAgent 完整执行。"
                ),
            }
            result["logs"].append(
                f"Batch {submission.batch_id} completed through durable agent commands."
            )
    except Exception as exc:
        result["validation"] = {"ok": False, "message": str(exc)}
        result["logs"].append(f"Pipeline failed: {exc}")
    finally:
        if database:
            database.dispose()
    return result


def run_two_vehicle_scenario(
    *,
    pickup_locations: tuple[str, str],
    dropoff_locations: tuple[str, str],
    cargo_names: tuple[str, str],
    database_url: str,
    reset_before_run: bool = True,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "natural_language": None,
        "model": "two-vehicle-scenario",
        "translation": None,
        "validation": {"ok": False},
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
            scenario_service = DemoScenarioService(session)
            if reset_before_run:
                reset = scenario_service.reset_demo_runtime()
                result["logs"].append(
                    f"Reset demo runtime before scenario: {reset}."
                )
            _refresh_demo_telemetry(session)
            scenario = scenario_service.create_two_vehicle_scenario(
                pickup_location_texts=pickup_locations,
                dropoff_location_texts=dropoff_locations,
                cargo_names=cargo_names,
            )
            result["order"] = {
                "batch_id": scenario.batch_id,
                "status": "ASSIGNED",
                "pickup_locations": list(pickup_locations),
                "dropoff_locations": list(dropoff_locations),
                "orders": [
                    {
                        "id": order.order_id,
                        "status": "ASSIGNED",
                        "formal_order": (
                            order.formal_order.model_dump(mode="json")
                            if order.formal_order
                            else None
                        ),
                    }
                    for order in scenario.orders
                ],
            }
            result["dispatch"] = {
                "assigned": True,
                "assigned_count": len(scenario.dispatches),
                "results": [_dispatch_dict(item) for item in scenario.dispatches],
            }
            result["fleet_simulation"] = scenario.simulation
            result["validation"] = {
                "ok": True,
                "message": "双车、双取货点、双目标点场景已完成无冲突规划。",
            }
            result["logs"].append(
                f"Created batch {scenario.batch_id} with 2 independent vehicle missions."
            )
    except Exception as exc:
        result["validation"] = {"ok": False, "message": str(exc)}
        result["logs"].append(f"Two-vehicle scenario failed: {exc}")
    finally:
        database.dispose()
    return result


def reset_demo_runtime(database_url: str) -> str:
    database = Database(database_url)
    try:
        with database.session() as session:
            reset = DemoScenarioService(session).reset_demo_runtime()
        return (
            f"演示数据已重置：删除 {reset['orders']} 个订单、{reset['missions']} 个 Mission，"
            f"恢复 {reset['vehicles']} 辆车。"
        )
    finally:
        database.dispose()


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


def render_fleet_dashboard(
    database_url: str,
    *,
    route_snapshot: Optional[FleetSnapshot] = None,
) -> None:
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
    route_by_vehicle = {
        vehicle.id: vehicle for vehicle in (route_snapshot.vehicles if route_snapshot else ())
    }
    selected = st.selectbox(
        "聚焦车辆",
        [""] + list(labels),
        format_func=lambda value: "全部车辆" if not value else labels[value],
        key="fleet_selected_vehicle",
    )
    map_column, fleet_column = st.columns([2.15, 1])
    with map_column:
        st.image(
            render_fleet_svg(
                map_data,
                snapshot,
                selected_vehicle_id=selected or None,
                route_snapshot=route_snapshot,
                show_route_endpoints=True,
            ),
            width="stretch",
        )
        st.caption(
            "虚线表示最近一次调度的规划路线；“起/终”标记和 V 编号表示"
            "每辆车的规划起点与终点。聚焦车辆后会突出对应路线。"
        )
    with fleet_column:
        st.dataframe(
            [
                {
                    "车辆": vehicle.name,
                    "状态": vehicle.status.value,
                    "电量": f"{vehicle.battery_level:.0f}%",
                    "节点": vehicle.node_id,
                    "规划起点": (
                        route_by_vehicle[vehicle.id].planned_node_ids[0]
                        if vehicle.id in route_by_vehicle
                        and route_by_vehicle[vehicle.id].planned_node_ids
                        else "—"
                    ),
                    "规划终点": (
                        route_by_vehicle[vehicle.id].planned_node_ids[-1]
                        if vehicle.id in route_by_vehicle
                        and route_by_vehicle[vehicle.id].planned_node_ids
                        else "—"
                    ),
                    "货物": (
                        route_by_vehicle.get(vehicle.id).cargo_name
                        if route_by_vehicle.get(vehicle.id)
                        else vehicle.cargo_name
                    ) or "—",
                    "取货": (
                        route_by_vehicle.get(vehicle.id).pickup_location_id
                        if route_by_vehicle.get(vehicle.id)
                        else vehicle.pickup_location_id
                    ) or "—",
                    "目标": (
                        route_by_vehicle.get(vehicle.id).dropoff_location_id
                        if route_by_vehicle.get(vehicle.id)
                        else vehicle.dropoff_location_id
                    ) or "—",
                    "订单": (
                        route_by_vehicle.get(vehicle.id).order_id
                        if route_by_vehicle.get(vehicle.id)
                        else vehicle.order_id
                    ) or "—",
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
    assigned_vehicle_label = dispatch.get("selected_vehicle_id")
    if not assigned_vehicle_label and dispatch.get("assigned_count"):
        assigned_vehicle_label = f"{dispatch['assigned_count']} 辆车"
    metric_cols[3].metric("调度车辆", assigned_vehicle_label or "未分配")
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
            for order in result["order"].get("orders", []):
                order["status"] = "DELIVERED"
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
    heading_column, replay_column = st.columns([5, 1])
    with heading_column:
        st.subheader("动态多车取货与送货过程")
    with replay_column:
        replay_clicked = st.button(
            "重播轨迹",
            width="stretch",
            key="runtime_replay_button",
        )
    if replay_clicked:
        st.session_state.last_frame_index = 0
        st.session_state.pop("fleet_runtime_slider", None)
        st.session_state.autoplay = True
        st.rerun()

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
    st.markdown("#### DispatcherAgent ↔ VehicleAgent 信息流")
    st.caption(
        "蓝色表示总控下发的 Mission、步骤和路由命令；"
        "橙色表示车辆 Agent 回传的接收、位置、阻塞和完成事件。"
    )
    flow_slot = st.empty()
    st.markdown("#### 多车路径与运行状态")
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
                flow_slot,
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
        flow_slot,
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
    flow_slot: Any,
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
    vehicle_views = {
        vehicle.id: vehicle for vehicle in simulation.snapshot.vehicles
    }
    route_frame = retain_completed_route_states(simulation, frame)
    flow_slot.image(
        render_agent_flow_svg(
            simulation,
            frame,
            selected_vehicle_id=selected_vehicle_id,
        ),
        width="stretch",
    )
    map_slot.image(
        render_fleet_svg(
            map_data,
            simulation.snapshot,
            selected_vehicle_id=selected_vehicle_id,
            runtime_frame=route_frame,
        ),
        width="stretch",
    )
    active_states = [state for state in route_frame.vehicles if state.mission_id]
    table_slot.dataframe(
        [
            {
                "车辆": vehicle_views[state.vehicle_id].name,
                "阶段": state.phase,
                "位置": state.node_id,
                "货物": state.cargo_name or "—",
                "载货": "是" if state.carrying_cargo else "否",
                "取货": vehicle_views[state.vehicle_id].pickup_location_id,
                "目标": vehicle_views[state.vehicle_id].dropoff_location_id,
                "订单": state.order_id,
            }
            for state in active_states
        ],
        width="stretch",
        hide_index=True,
    )
    caption_slot.caption(
        f"时间片 {frame.index + 1}/{len(simulation.frames)} ｜ "
        "实线为已行驶路线，虚线为剩余路线，黄色“货”标记表示车辆已装货；"
        "到达目标后保留完整已行驶路线。"
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
