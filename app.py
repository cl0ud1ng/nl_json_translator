from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import streamlit as st

from nl_json_translator.config import config_from_env, load_env_file
from nl_json_translator.deepseek_client import DeepSeekClient
from nl_json_translator.domain.schemas import TransportIntentDraft
from nl_json_translator.infrastructure.database import Database, default_database_url
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.map_executor import build_runtime_frames, execute_command, pretty_json
from nl_json_translator.prompts import build_messages
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.services.location_resolver import LocationResolution
from nl_json_translator.services.order_service import OrderService
from nl_json_translator.translator import Translator


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_REQUEST = "从 A 取 3 箱零件送到 B"
FRAME_DELAY_SECONDS = 0.12


def main() -> None:
    st.set_page_config(page_title="场内货物运输 Demo", layout="wide")
    load_env_file(ROOT_DIR / ".env")
    _init_state()
    database_url = default_database_url()
    seed_demo_data(database_url)
    location_names = _location_names(database_url)

    st.title("场内货物运输意图与单车执行 Demo")
    with st.sidebar:
        model = st.selectbox("模型", ["deepseek-v4-pro", "deepseek-v4-flash"], index=0)
        start_point = st.selectbox("车辆演示起点", location_names, index=0)
        show_prompt = st.toggle("显示 Prompt", value=False)
        st.divider()
        st.caption("自然语言 → 运输意图 → 地点解析 → 订单 → 单车取送路径")
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
    col_run, col_replay = st.columns(2)
    run_clicked = col_run.button("创建订单并播放", type="primary", width="stretch")
    replay_clicked = col_replay.button(
        "重播轨迹",
        width="stretch",
        disabled=not bool(st.session_state.last_result and st.session_state.last_result.get("frames")),
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
    if replay_clicked:
        st.session_state.last_frame_index = 0
        st.session_state.autoplay = True
    if st.session_state.last_result:
        render_result(
            st.session_state.last_result,
            show_prompt,
            autoplay=st.session_state.get("autoplay", False),
        )
        st.session_state.autoplay = False


def _init_state() -> None:
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("last_frame_index", 0)
    st.session_state.setdefault("request_text", DEFAULT_REQUEST)
    st.session_state.setdefault("autoplay", False)


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
        "internal_mission_command": None,
        "execution": None,
        "frames": [],
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
            result["internal_mission_command"] = internal_command
            result["execution"] = execute_command(
                internal_command, repository=repository, start=start_point
            )
            result["frames"] = build_runtime_frames(
                internal_command, repository=repository, start=start_point
            )
            result["logs"].append("Internal REPOSITION and TRANSPORT routes were simulated.")
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


def render_result(result: dict[str, Any], show_prompt: bool, *, autoplay: bool) -> None:
    translation = result.get("translation") or {}
    validation = result.get("validation") or {}
    order = result.get("order") or {}
    execution = result.get("execution") or {}
    frames = result.get("frames") or []
    st.subheader("运行结果")
    metric_cols = st.columns(4)
    metric_cols[0].metric("意图来源", translation.get("source", "none"))
    metric_cols[1].metric("意图校验", "通过" if validation.get("ok") else "失败")
    metric_cols[2].metric("订单状态", order.get("status", "未创建"))
    final_pose = execution.get("final_pose") or {}
    metric_cols[3].metric("最终位置", f"({final_pose.get('x', '-')}, {final_pose.get('y', '-')})")
    if validation.get("ok"):
        st.success(validation.get("message"))
    else:
        st.error(validation.get("message"))
    if order.get("status") == "NEEDS_REVIEW":
        st.warning("地点存在歧义，订单已进入 NEEDS_REVIEW，未执行路径。")
    render_runtime(frames, autoplay=autoplay)

    tab_order, tab_intent, tab_internal, tab_prompt, tab_log = st.tabs(
        ["订单", "运输意图", "内部执行", "Prompt", "日志"]
    )
    with tab_order:
        st.json(order, expanded=True)
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
        st.json(result, expanded=False)


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
    frame_slot.image(frame["svg"], use_container_width=True)
    status_slot.caption(
        f"Frame {index + 1}/{total} | Step {frame.get('step')} | {frame.get('action')} | "
        f"{frame.get('detail')} | Pose ({pose.get('x')}, {pose.get('y')}), "
        f"heading {pose.get('heading')}°"
    )
    progress_slot.progress((index + 1) / total)


if __name__ == "__main__":
    main()
