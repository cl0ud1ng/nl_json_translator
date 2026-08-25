from __future__ import annotations

import html
from typing import Optional

from nl_json_translator.domain.enums import VehicleStatus
from nl_json_translator.services.fleet_simulation_service import (
    FleetRuntimeFrame,
    FleetSimulation,
    VehicleRuntimeState,
)


FLOW_WIDTH = 1120
HEADER_HEIGHT = 92
LANE_HEIGHT = 142


def render_agent_flow_svg(
    simulation: FleetSimulation,
    frame: FleetRuntimeFrame,
    *,
    selected_vehicle_id: Optional[str] = None,
) -> str:
    """Render DispatcherAgent and every VehicleAgent as synchronized message lanes."""

    vehicles = simulation.snapshot.vehicles
    height = HEADER_HEIGHT + max(1, len(vehicles)) * LANE_HEIGHT + 24
    effective_states = tuple(
        _effective_state(simulation, frame, vehicle.id) for vehicle in vehicles
    )
    active_count = sum(
        state.mission_id is not None and state.phase != "任务完成"
        for state in effective_states
    )
    completed_count = sum(
        state.phase == "任务完成" for state in effective_states
    )
    parts = [
        f'<svg viewBox="0 0 {FLOW_WIDTH} {height}" xmlns="http://www.w3.org/2000/svg" '
        'role="img" aria-label="DispatcherAgent to VehicleAgent information flow">',
        "<defs>",
        '<marker id="flow-out" markerWidth="9" markerHeight="9" refX="8" refY="4.5" '
        'orient="auto"><path d="M0,0 L9,4.5 L0,9 Z" fill="#2563eb"/></marker>',
        '<marker id="flow-in" markerWidth="9" markerHeight="9" refX="8" refY="4.5" '
        'orient="auto"><path d="M0,0 L9,4.5 L0,9 Z" fill="#f97316"/></marker>',
        '<filter id="flow-shadow" x="-20%" y="-20%" width="140%" height="140%">'
        '<feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#0f172a" '
        'flood-opacity="0.14"/></filter>',
        "</defs>",
        '<rect width="100%" height="100%" rx="18" fill="#f8fafc"/>',
        '<text x="28" y="34" fill="#0f172a" font-size="20" font-weight="700">'
        'Agent 命令 / 事件信息流</text>',
        f'<text x="28" y="60" fill="#64748b" font-size="13">'
        f'时间片 {frame.index + 1}/{len(simulation.frames)} · '
        f'执行中 {active_count} · 已完成 {completed_count}</text>',
        '<g transform="translate(680 30)">',
        '<line x1="0" y1="0" x2="54" y2="0" stroke="#2563eb" stroke-width="3" '
        'marker-end="url(#flow-out)"/><text x="64" y="5" fill="#334155" '
        'font-size="12">总控 → 车辆：命令 / 路由</text>',
        '<line x1="54" y1="28" x2="0" y2="28" stroke="#f97316" stroke-width="3" '
        'marker-end="url(#flow-in)"/><text x="64" y="33" fill="#334155" '
        'font-size="12">车辆 → 总控：事件 / 心跳</text></g>',
    ]

    controller_top = HEADER_HEIGHT + 10
    controller_height = max(110, len(vehicles) * LANE_HEIGHT - 20)
    parts.extend(
        [
            f'<rect x="24" y="{controller_top}" width="232" '
            f'height="{controller_height}" rx="16" fill="#0f766e" '
            'filter="url(#flow-shadow)"/>',
            f'<text x="48" y="{controller_top + 38}" fill="#ffffff" '
            'font-size="18" font-weight="700">DispatcherAgent</text>',
            f'<text x="48" y="{controller_top + 63}" fill="#ccfbf1" '
            'font-size="12">dispatcher/main · 唯一总控</text>',
            f'<text x="48" y="{controller_top + 94}" fill="#ffffff" '
            f'font-size="13">Mission：{len(simulation.mission_ids)}</text>',
            f'<text x="48" y="{controller_top + 118}" fill="#ffffff" '
            'font-size="13">责任：分配 · 路由 · 预约</text>',
        ]
    )

    for index, vehicle in enumerate(vehicles):
        center_y = HEADER_HEIGHT + index * LANE_HEIGHT + LANE_HEIGHT / 2
        state = effective_states[index]
        outgoing, incoming = _messages(frame.index, state)
        selected = not selected_vehicle_id or vehicle.id == selected_vehicle_id
        opacity = 1.0 if selected else 0.25
        agent_status = _agent_status(state)
        status_color = _status_color(state)
        mission_label = _short_id(state.mission_id, "mission") if state.mission_id else "无 Mission"
        order_label = _short_id(state.order_id, "order") if state.order_id else "等待订单"
        cargo_label = state.cargo_name or "未载货"
        parts.extend(
            [
                f'<g data-agent-id="vehicle/{html.escape(vehicle.id)}" opacity="{opacity}">',
                f'<rect x="278" y="{center_y - 58}" width="424" height="116" '
                f'rx="13" fill="{("#ffffff" if index % 2 == 0 else "#f1f5f9")}" '
                'stroke="#cbd5e1"/>',
                f'<line x1="256" y1="{center_y - 17}" x2="748" y2="{center_y - 17}" '
                'stroke="#2563eb" stroke-width="3" marker-end="url(#flow-out)"/>',
                f'<circle cx="283" cy="{center_y - 17}" r="5" fill="#2563eb"/>',
                f'<rect x="386" y="{center_y - 34}" width="210" height="27" rx="7" '
                'fill="#dbeafe" stroke="#93c5fd"/>',
                f'<text x="491" y="{center_y - 16}" fill="#1e3a8a" font-size="12" '
                f'text-anchor="middle" font-weight="700">{html.escape(outgoing)}</text>',
                f'<line x1="748" y1="{center_y + 25}" x2="256" y2="{center_y + 25}" '
                'stroke="#f97316" stroke-width="3" marker-end="url(#flow-in)"/>',
                f'<circle cx="722" cy="{center_y + 25}" r="5" fill="#f97316"/>',
                f'<rect x="386" y="{center_y + 8}" width="210" height="27" rx="7" '
                'fill="#ffedd5" stroke="#fdba74"/>',
                f'<text x="491" y="{center_y + 26}" fill="#9a3412" font-size="12" '
                f'text-anchor="middle" font-weight="700">{html.escape(incoming)}</text>',
                f'<rect x="754" y="{center_y - 55}" width="338" height="110" rx="14" '
                f'fill="#ffffff" stroke="{html.escape(vehicle.color)}" stroke-width="3" '
                'filter="url(#flow-shadow)"/>',
                f'<circle cx="779" cy="{center_y - 28}" r="9" fill="{status_color}"/>',
                f'<text x="797" y="{center_y - 22}" fill="#0f172a" font-size="16" '
                f'font-weight="700">{html.escape(vehicle.name)}</text>',
                f'<text x="1067" y="{center_y - 23}" fill="{status_color}" '
                f'font-size="12" text-anchor="end" font-weight="700">{agent_status}</text>',
                f'<text x="776" y="{center_y + 2}" fill="#334155" font-size="12">'
                f'{html.escape(state.phase)} · {html.escape(state.node_id)}</text>',
                f'<text x="776" y="{center_y + 25}" fill="#64748b" font-size="11">'
                f'{html.escape(mission_label)} · {html.escape(order_label)}</text>',
                f'<text x="776" y="{center_y + 45}" fill="#64748b" font-size="11">'
                f'{html.escape(cargo_label)} · '
                f'{("已载货" if state.carrying_cargo else "未载货")}</text>',
                "</g>",
            ]
        )
    parts.append("</svg>")
    return "".join(parts)


def _effective_state(
    simulation: FleetSimulation, frame: FleetRuntimeFrame, vehicle_id: str
) -> VehicleRuntimeState:
    current = next(state for state in frame.vehicles if state.vehicle_id == vehicle_id)
    if current.mission_id:
        return current
    vehicle = next(item for item in simulation.snapshot.vehicles if item.id == vehicle_id)
    if not vehicle.mission_id:
        return current
    for previous in reversed(simulation.frames[: frame.index + 1]):
        state = next(item for item in previous.vehicles if item.vehicle_id == vehicle_id)
        if state.mission_id:
            return state
    return current


def _messages(time_slot: int, state: VehicleRuntimeState) -> tuple[str, str]:
    if not state.mission_id:
        return "NoCommand", "Heartbeat · READY"
    if time_slot == 0:
        return "AssignMission · Route v1", "CommandAccepted"
    if state.phase == "任务完成":
        return "ReleaseReservation", "MissionCompleted"
    if state.status is VehicleStatus.BLOCKED:
        return "Hold / WaitReservation", "VehicleBlocked"
    if state.status is VehicleStatus.LOADING:
        return "ExecuteStep · LOAD", (
            "CargoLoaded" if state.phase == "装货完成" else "StepProgress · LOAD"
        )
    if state.status is VehicleStatus.UNLOADING:
        return "ExecuteStep · UNLOAD", (
            "CargoUnloaded" if state.phase == "卸货完成" else "StepProgress · UNLOAD"
        )
    if state.status is VehicleStatus.TO_DROPOFF:
        return "ExecuteStep · TRANSPORT", f"PositionUpdated · {state.node_id}"
    if state.status is VehicleStatus.TO_PICKUP:
        return "ExecuteStep · REPOSITION", f"PositionUpdated · {state.node_id}"
    return "MissionControl", f"Heartbeat · {state.status.value}"


def _agent_status(state: VehicleRuntimeState) -> str:
    if state.phase == "任务完成":
        return "READY · COMPLETED"
    if not state.mission_id:
        return "READY"
    if state.status is VehicleStatus.BLOCKED:
        return "BLOCKED"
    return "RUNNING"


def _status_color(state: VehicleRuntimeState) -> str:
    if state.phase == "任务完成" or not state.mission_id:
        return "#16a34a"
    if state.status is VehicleStatus.BLOCKED:
        return "#dc2626"
    return "#2563eb"


def _short_id(value: Optional[str], prefix: str) -> str:
    if not value:
        return "—"
    suffix = value.removeprefix(f"{prefix}_")
    return f"{prefix}_{suffix[:8]}"
