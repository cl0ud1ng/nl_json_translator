from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import streamlit as st

from nl_json_translator.config import config_from_env, load_env_file
from nl_json_translator.deepseek_client import DeepSeekClient
from nl_json_translator.map_executor import POINTS, build_runtime_frames, execute_command, pretty_json
from nl_json_translator.prompts import build_messages
from nl_json_translator.schema import validate_command
from nl_json_translator.translator import Translator


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_COMMAND = "go to B then A"
FRAME_DELAY_SECONDS = 0.16


def main() -> None:
    st.set_page_config(page_title="NL-to-JSON Car Agent", layout="wide")
    load_env_file(ROOT_DIR / ".env")
    _init_state()

    st.title("NL-to-JSON Unmanned-Car Runtime")

    with st.sidebar:
        model = st.selectbox("模型", ["deepseek-v4-pro", "deepseek-v4-flash"], index=0)
        start_point = st.selectbox("起点", list(POINTS.keys()), index=0)
        show_prompt = st.toggle("显示 Prompt", value=False)
        st.divider()
        st.caption("流程：自然语言 -> 结构化 JSON -> Schema 校验 -> 动态地图执行")
        if st.button("清空结果", width="stretch"):
            st.session_state.last_result = None
            st.session_state.last_frame_index = 0
            st.rerun()

    nl_command = st.text_area("自然语言命令", value=st.session_state.get("nl_command", DEFAULT_COMMAND), height=90)
    st.session_state.nl_command = nl_command

    col_run, col_replay = st.columns([1, 1])
    run_clicked = col_run.button("运行并播放", type="primary", width="stretch")
    replay_clicked = col_replay.button(
        "重播轨迹",
        width="stretch",
        disabled=not bool(st.session_state.last_result and st.session_state.last_result.get("frames")),
    )

    if run_clicked:
        with st.spinner("Pipeline running..."):
            st.session_state.last_result = run_pipeline(
                nl_command=nl_command,
                model=model,
                start_point=start_point,
            )
            st.session_state.last_frame_index = 0
            st.session_state.autoplay = True

    if replay_clicked:
        st.session_state.last_frame_index = 0
        st.session_state.autoplay = True

    if st.session_state.last_result:
        render_result(st.session_state.last_result, show_prompt, autoplay=st.session_state.get("autoplay", False))
        st.session_state.autoplay = False


def _init_state() -> None:
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("last_frame_index", 0)
    st.session_state.setdefault("nl_command", DEFAULT_COMMAND)
    st.session_state.setdefault("autoplay", False)


def run_pipeline(
    *,
    nl_command: str,
    model: str,
    start_point: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "natural_language": nl_command,
        "model": model,
        "start_point": start_point,
        "translation": None,
        "validation": {"ok": False},
        "execution": None,
        "frames": [],
        "prompt_messages": build_messages(nl_command) if nl_command.strip() else [],
        "logs": [],
    }

    try:
        config = config_from_env(model=model)
        translator = Translator(DeepSeekClient(config))
        translated = translator.translate(nl_command)
        command = translated.command
        result["translation"] = {
            "source": "deepseek",
            "command": command,
            "raw_response": translated.raw_response,
            "attempts": translated.attempts,
        }
        result["logs"].append(f"DeepSeek translation completed in {translated.attempts} attempt(s).")

        validate_command(command)
        result["validation"] = {"ok": True, "message": "Schema validation passed."}
        result["logs"].append("JSON command passed schema validation.")

        execution = execute_command(command, start=start_point)
        frames = build_runtime_frames(command, start=start_point)
        result["execution"] = execution
        result["frames"] = frames
        result["logs"].append(f"Execution produced {len(execution['timeline'])} high-level step(s).")
        result["logs"].append(f"Runtime animation produced {len(frames)} frame(s).")
        if execution["warnings"]:
            result["logs"].extend(execution["warnings"])
    except Exception as exc:
        result["validation"] = {"ok": False, "message": str(exc)}
        result["logs"].append(f"Pipeline failed: {exc}")

    return result


def render_result(result: dict[str, Any], show_prompt: bool, *, autoplay: bool) -> None:
    translation = result.get("translation") or {}
    validation = result.get("validation") or {}
    execution = result.get("execution") or {}
    frames = result.get("frames") or []

    st.subheader("运行结果")
    metric_cols = st.columns(4)
    metric_cols[0].metric("翻译来源", translation.get("source", "none"))
    metric_cols[1].metric("JSON 校验", "通过" if validation.get("ok") else "失败")
    metric_cols[2].metric("动画帧数", len(frames))
    final_pose = execution.get("final_pose") or {}
    metric_cols[3].metric("最终位置", f"({final_pose.get('x', '-')}, {final_pose.get('y', '-')})")

    if validation.get("ok"):
        st.success(validation.get("message"))
    else:
        st.error(validation.get("message"))

    render_runtime(frames, autoplay=autoplay)

    tab_steps, tab_json, tab_prompt, tab_log = st.tabs(["步骤", "JSON", "Prompt", "日志"])

    with tab_steps:
        render_steps(result)
    with tab_json:
        command = translation.get("command")
        if command:
            st.code(pretty_json(command), language="json")
        raw = translation.get("raw_response")
        if raw:
            with st.expander("Raw model response", expanded=False):
                st.code(raw, language="json")
    with tab_prompt:
        if show_prompt and result.get("prompt_messages"):
            st.json(result["prompt_messages"], expanded=False)
        else:
            st.write("Enable '显示 Prompt' in the sidebar to inspect the prompt.")
    with tab_log:
        st.json(result, expanded=False)


def render_runtime(frames: list[dict[str, Any]], *, autoplay: bool) -> None:
    st.subheader("动态地图执行")
    if not frames:
        st.info("Run a command to see the unmanned car move on the map.")
        return

    frame_slot = st.empty()
    status_slot = st.empty()
    progress_slot = st.empty()

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
        f"{frame.get('detail')} | Pose ({pose.get('x')}, {pose.get('y')}), heading {pose.get('heading')} deg"
    )
    progress_slot.progress((index + 1) / total)


def render_steps(result: dict[str, Any]) -> None:
    st.write("Pipeline")
    rows = [
        {"stage": "1. Natural language input", "status": "done", "detail": result.get("natural_language", "")},
        {
            "stage": "2. LLM translation",
            "status": "done" if result.get("translation") else "failed",
            "detail": (result.get("translation") or {}).get("source", ""),
        },
        {
            "stage": "3. JSON validation",
            "status": "passed" if result.get("validation", {}).get("ok") else "failed",
            "detail": result.get("validation", {}).get("message", ""),
        },
        {
            "stage": "4. Command execution",
            "status": "done" if result.get("execution") else "not run",
            "detail": f"{len((result.get('execution') or {}).get('timeline', []))} step(s)",
        },
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    execution = result.get("execution")
    if execution:
        st.write("Execution timeline")
        st.dataframe(execution["timeline"], width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
