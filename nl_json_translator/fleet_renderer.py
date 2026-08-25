from __future__ import annotations

import html
from typing import Optional

from nl_json_translator.repositories.maps import MapData
from nl_json_translator.services.fleet_simulation_service import (
    FleetRuntimeFrame,
    FleetSimulation,
)
from nl_json_translator.services.fleet_view_service import FleetSnapshot, FleetVehicleView


CELL_SIZE = 34
STATUS_COLORS = {
    "IDLE": "#16a34a",
    "RESERVED": "#f59e0b",
    "TO_PICKUP": "#0ea5e9",
    "LOADING": "#8b5cf6",
    "TO_DROPOFF": "#2563eb",
    "UNLOADING": "#7c3aed",
    "CHARGING": "#eab308",
    "BLOCKED": "#dc2626",
    "OFFLINE": "#64748b",
    "FAILED": "#991b1b",
}


def render_fleet_svg(
    map_data: MapData,
    snapshot: FleetSnapshot,
    *,
    selected_vehicle_id: Optional[str] = None,
    runtime_frame: Optional[FleetRuntimeFrame] = None,
    route_snapshot: Optional[FleetSnapshot] = None,
    show_route_endpoints: bool = False,
) -> str:
    width = map_data.width * CELL_SIZE
    height = map_data.height * CELL_SIZE
    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        'role="img" aria-label="Multi-vehicle dispatch map">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
    ]
    _draw_grid(parts, map_data, width, height)
    _draw_obstacles(parts, map_data)
    route_source = route_snapshot or snapshot
    _draw_routes(parts, map_data, route_source, selected_vehicle_id, runtime_frame)
    _draw_locations(parts, map_data)
    _draw_vehicles(parts, map_data, snapshot, selected_vehicle_id, runtime_frame)
    if show_route_endpoints:
        _draw_route_endpoints(parts, map_data, route_source, selected_vehicle_id)
    parts.append("</svg>")
    return "".join(parts)


def _draw_grid(parts: list[str], map_data: MapData, width: int, height: int) -> None:
    for x in range(map_data.width + 1):
        parts.append(
            f'<path d="M{x * CELL_SIZE} 0 V{height}" stroke="#e2e8f0" stroke-width="1"/>'
        )
    for y in range(map_data.height + 1):
        parts.append(
            f'<path d="M0 {y * CELL_SIZE} H{width}" stroke="#e2e8f0" stroke-width="1"/>'
        )


def _draw_obstacles(parts: list[str], map_data: MapData) -> None:
    for y in range(map_data.height):
        for x in range(map_data.width):
            if map_data.node_at((x, y)):
                continue
            parts.append(
                f'<rect x="{x * CELL_SIZE + 4}" y="{y * CELL_SIZE + 4}" '
                f'width="{CELL_SIZE - 8}" height="{CELL_SIZE - 8}" rx="4" '
                'fill="#334155" opacity="0.9"/>'
            )


def _draw_routes(
    parts: list[str],
    map_data: MapData,
    snapshot: FleetSnapshot,
    selected_vehicle_id: Optional[str],
    runtime_frame: Optional[FleetRuntimeFrame],
) -> None:
    runtime_by_vehicle = (
        {state.vehicle_id: state for state in runtime_frame.vehicles}
        if runtime_frame
        else {}
    )
    ordered = sorted(
        snapshot.vehicles,
        key=lambda vehicle: vehicle.id == selected_vehicle_id,
    )
    for vehicle in ordered:
        selected = vehicle.id == selected_vehicle_id
        opacity = 0.95 if selected or not selected_vehicle_id else 0.22
        runtime = runtime_by_vehicle.get(vehicle.id)
        if runtime:
            _draw_route_line(
                parts,
                map_data,
                vehicle,
                runtime.executed_node_ids,
                kind="executed",
                width=7 if selected else 5,
                opacity=opacity,
                dashed=False,
            )
            remaining = (
                (runtime.node_id,) + runtime.remaining_node_ids
                if runtime.remaining_node_ids
                else ()
            )
            _draw_route_line(
                parts,
                map_data,
                vehicle,
                remaining,
                kind="remaining",
                width=6 if selected else 4,
                opacity=opacity * 0.72,
                dashed=True,
            )
            continue
        _draw_route_line(
            parts,
            map_data,
            vehicle,
            vehicle.planned_node_ids,
            kind="planned",
            width=7 if selected else 4,
            opacity=opacity,
            dashed=True,
        )


def _draw_route_line(
    parts: list[str],
    map_data: MapData,
    vehicle: FleetVehicleView,
    node_ids: tuple[str, ...],
    *,
    kind: str,
    width: int,
    opacity: float,
    dashed: bool,
) -> None:
    points = _route_points(map_data, node_ids)
    if len(points) < 2:
        return
    coordinates = " ".join(f"{x},{y}" for x, y in points)
    dash_attribute = ' stroke-dasharray="10 7"' if dashed else ""
    parts.append(
        f'<polyline data-vehicle-id="{html.escape(vehicle.id)}" '
        f'data-route-kind="{kind}" points="{coordinates}" fill="none" '
        f'stroke="{vehicle.color}" stroke-width="{width}"{dash_attribute} '
        f'stroke-linecap="round" stroke-linejoin="round" opacity="{opacity}"/>'
    )


def _draw_locations(parts: list[str], map_data: MapData) -> None:
    for location in map_data.locations.values():
        node = map_data.nodes[location.node_id]
        center_x, center_y = _node_center(node.x, node.y)
        parts.append(
            f'<circle cx="{center_x}" cy="{center_y}" r="11" '
            f'fill="{html.escape(location.color)}" stroke="#fff" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{center_x}" y="{center_y + 4}" fill="#fff" font-size="9" '
            f'font-weight="700" text-anchor="middle">{html.escape(location.label)}</text>'
        )


def _draw_route_endpoints(
    parts: list[str],
    map_data: MapData,
    snapshot: FleetSnapshot,
    selected_vehicle_id: Optional[str],
) -> None:
    occurrences: dict[tuple[str, str], int] = {}
    route_vehicles = [vehicle for vehicle in snapshot.vehicles if vehicle.planned_node_ids]
    endpoint_counts: dict[tuple[str, str], int] = {}
    for vehicle in route_vehicles:
        for kind, node_id in (
            ("start", vehicle.planned_node_ids[0]),
            ("end", vehicle.planned_node_ids[-1]),
        ):
            endpoint_counts[(kind, node_id)] = endpoint_counts.get((kind, node_id), 0) + 1
    for route_index, vehicle in enumerate(route_vehicles, start=1):
        selected = not selected_vehicle_id or vehicle.id == selected_vehicle_id
        opacity = 1.0 if selected else 0.24
        endpoints = (
            ("start", vehicle.planned_node_ids[0], "起", -1),
            ("end", vehicle.planned_node_ids[-1], "终", 1),
        )
        for kind, node_id, label, vertical_direction in endpoints:
            node = map_data.nodes.get(node_id)
            if not node:
                continue
            occurrence_key = (kind, node_id)
            occurrence = occurrences.get(occurrence_key, 0)
            occurrences[occurrence_key] = occurrence + 1
            center_x, center_y = _node_center(node.x, node.y)
            endpoint_count = endpoint_counts[occurrence_key]
            offset_x = (occurrence - (endpoint_count - 1) / 2) * 30
            offset_y = -50 if vertical_direction < 0 else 28
            marker_x = min(max(15, center_x + offset_x), map_data.width * CELL_SIZE - 15)
            marker_y = min(max(15, center_y + offset_y), map_data.height * CELL_SIZE - 15)
            parts.extend(
                [
                    f'<g data-route-endpoint="{kind}" '
                    f'data-vehicle-id="{html.escape(vehicle.id)}" opacity="{opacity}">',
                    f'<line x1="{center_x}" y1="{center_y}" x2="{marker_x}" '
                    f'y2="{marker_y}" stroke="{html.escape(vehicle.color)}" '
                    'stroke-width="2" stroke-dasharray="3 3"/>',
                    f'<circle cx="{marker_x}" cy="{marker_y}" r="13" fill="#ffffff" '
                    f'stroke="{html.escape(vehicle.color)}" stroke-width="3"/>',
                    f'<text x="{marker_x}" y="{marker_y - 1}" '
                    f'fill="{html.escape(vehicle.color)}" font-size="7" font-weight="800" '
                    f'text-anchor="middle">V{route_index}</text>',
                    f'<text x="{marker_x}" y="{marker_y + 8}" '
                    f'fill="{html.escape(vehicle.color)}" font-size="9" font-weight="800" '
                    f'text-anchor="middle">{label}</text>',
                    f'<title>{html.escape(vehicle.name)} {label}点 · {html.escape(node_id)}</title>',
                    "</g>",
                ]
            )


def _draw_vehicles(
    parts: list[str],
    map_data: MapData,
    snapshot: FleetSnapshot,
    selected_vehicle_id: Optional[str],
    runtime_frame: Optional[FleetRuntimeFrame],
) -> None:
    runtime_by_vehicle = (
        {state.vehicle_id: state for state in runtime_frame.vehicles}
        if runtime_frame
        else {}
    )
    for vehicle in snapshot.vehicles:
        runtime = runtime_by_vehicle.get(vehicle.id)
        node_id = runtime.node_id if runtime else vehicle.node_id
        heading = runtime.heading if runtime else vehicle.heading
        status = runtime.status if runtime else vehicle.status
        node = map_data.nodes.get(node_id)
        if not node:
            continue
        center_x, center_y = _node_center(node.x, node.y)
        selected = vehicle.id == selected_vehicle_id
        outline = STATUS_COLORS.get(status.value, "#475569")
        if selected:
            parts.append(
                f'<circle cx="{center_x}" cy="{center_y}" r="18" fill="none" '
                f'stroke="{vehicle.color}" stroke-width="4" opacity="0.45"/>'
            )
        parts.append(
            f'<g data-vehicle-id="{html.escape(vehicle.id)}" '
            f'transform="translate({center_x} {center_y}) rotate({heading})">'
            f'<path d="M14 0 L-10 -9 L-6 0 L-10 9 Z" fill="{vehicle.color}" '
            f'stroke="{outline}" stroke-width="3"/></g>'
        )
        label = (
            f"{vehicle.name} · {runtime.phase}"
            if runtime
            else f"{vehicle.name} · {status.value}"
        )
        label_width = min(176, max(92, len(label) * 6 + 16))
        label_x = max(
            2,
            min(
                center_x - label_width / 2,
                map_data.width * CELL_SIZE - label_width - 2,
            ),
        )
        label_y = max(2, center_y - 34)
        parts.append(
            f'<rect x="{label_x}" y="{label_y}" width="{label_width}" height="18" '
            'rx="6" fill="#0f172a" opacity="0.88"/>'
        )
        parts.append(
            f'<text x="{label_x + label_width / 2}" y="{label_y + 12.5}" fill="#fff" '
            f'font-size="9" font-weight="600" text-anchor="middle">{html.escape(label)}</text>'
        )
        if runtime and runtime.carrying_cargo:
            parts.append(
                f'<rect x="{center_x + 7}" y="{center_y + 6}" width="20" height="15" '
                'rx="4" fill="#facc15" stroke="#854d0e" stroke-width="1.5"/>'
            )
            parts.append(
                f'<text x="{center_x + 17}" y="{center_y + 17}" fill="#422006" '
                'font-size="9" font-weight="800" text-anchor="middle">货</text>'
            )


def _route_points(map_data: MapData, node_ids: tuple[str, ...]) -> list[tuple[float, float]]:
    points = []
    for node_id in node_ids:
        node = map_data.nodes.get(node_id)
        if node:
            points.append(_node_center(node.x, node.y))
    return points


def _node_center(x: int, y: int) -> tuple[float, float]:
    return x * CELL_SIZE + CELL_SIZE / 2, y * CELL_SIZE + CELL_SIZE / 2


def retain_completed_route_states(
    simulation: FleetSimulation,
    frame: FleetRuntimeFrame,
) -> FleetRuntimeFrame:
    """Keep a completed vehicle's final executed route visible in later frames."""

    states = []
    for current in frame.vehicles:
        if current.mission_id:
            states.append(current)
            continue
        completed = None
        for previous in reversed(simulation.frames[: frame.index + 1]):
            candidate = next(
                state
                for state in previous.vehicles
                if state.vehicle_id == current.vehicle_id
            )
            if candidate.mission_id and candidate.phase == "任务完成":
                completed = candidate
                break
        states.append(completed or current)
    return FleetRuntimeFrame(index=frame.index, vehicles=tuple(states))
