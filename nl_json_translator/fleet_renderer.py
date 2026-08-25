from __future__ import annotations

import html
from typing import Optional

from nl_json_translator.repositories.maps import MapData
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
    _draw_routes(parts, map_data, snapshot, selected_vehicle_id)
    _draw_locations(parts, map_data)
    _draw_vehicles(parts, map_data, snapshot, selected_vehicle_id)
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
) -> None:
    ordered = sorted(
        snapshot.vehicles,
        key=lambda vehicle: vehicle.id == selected_vehicle_id,
    )
    for vehicle in ordered:
        points = _route_points(map_data, vehicle.planned_node_ids)
        if len(points) < 2:
            continue
        selected = vehicle.id == selected_vehicle_id
        coordinates = " ".join(f"{x},{y}" for x, y in points)
        parts.append(
            f'<polyline data-vehicle-id="{html.escape(vehicle.id)}" points="{coordinates}" '
            f'fill="none" stroke="{vehicle.color}" stroke-width="{7 if selected else 4}" '
            f'stroke-dasharray="10 7" stroke-linecap="round" stroke-linejoin="round" '
            f'opacity="{0.95 if selected or not selected_vehicle_id else 0.28}"/>'
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


def _draw_vehicles(
    parts: list[str],
    map_data: MapData,
    snapshot: FleetSnapshot,
    selected_vehicle_id: Optional[str],
) -> None:
    for vehicle in snapshot.vehicles:
        node = map_data.nodes.get(vehicle.node_id)
        if not node:
            continue
        center_x, center_y = _node_center(node.x, node.y)
        selected = vehicle.id == selected_vehicle_id
        outline = STATUS_COLORS.get(vehicle.status.value, "#475569")
        if selected:
            parts.append(
                f'<circle cx="{center_x}" cy="{center_y}" r="18" fill="none" '
                f'stroke="{vehicle.color}" stroke-width="4" opacity="0.45"/>'
            )
        parts.append(
            f'<g data-vehicle-id="{html.escape(vehicle.id)}" '
            f'transform="translate({center_x} {center_y}) rotate({vehicle.heading})">'
            f'<path d="M14 0 L-10 -9 L-6 0 L-10 9 Z" fill="{vehicle.color}" '
            f'stroke="{outline}" stroke-width="3"/></g>'
        )
        label = f"{vehicle.name} · {vehicle.status.value}"
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


def _route_points(map_data: MapData, node_ids: tuple[str, ...]) -> list[tuple[float, float]]:
    points = []
    for node_id in node_ids:
        node = map_data.nodes.get(node_id)
        if node:
            points.append(_node_center(node.x, node.y))
    return points


def _node_center(x: int, y: int) -> tuple[float, float]:
    return x * CELL_SIZE + CELL_SIZE / 2, y * CELL_SIZE + CELL_SIZE / 2
