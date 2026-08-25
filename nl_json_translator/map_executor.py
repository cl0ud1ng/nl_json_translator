from __future__ import annotations

import html
import json
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Any

from .repositories.maps import MapData, MapLocationData, MapNodeData, MapRepository


CELL_SIZE = 34


@dataclass
class Pose:
    x: int
    y: int
    heading: float = 0.0


def execute_command(
    command: dict[str, Any], *, repository: MapRepository, start: str = "A"
) -> dict[str, Any]:
    map_data = repository.load()
    start_node, _ = require_start_node(map_data, start)
    pose = Pose(x=start_node.x, y=start_node.y, heading=0.0)
    timeline: list[dict[str, Any]] = []
    executed_path = [{"x": pose.x, "y": pose.y}]
    warnings: list[str] = []

    for index, action in enumerate(flatten_actions(command), start=1):
        action_name = action.get("action")
        if action_name == "stop":
            timeline.append({"step": index, "action": "stop", "detail": "Execution stopped"})
            break

        if action_name == "go_to_goal":
            value = action.get("params", {}).get("location", {}).get("value")
            target = require_location(map_data, value)
            target_node = map_data.nodes[target.node_id]
            path = astar(
                {"x": pose.x, "y": pose.y},
                {"x": target_node.x, "y": target_node.y},
                map_data,
            )
            if not path:
                raise ValueError(f'No A* path from ({pose.x}, {pose.y}) to "{target.name}".')
            if len(path) > 1:
                pose.heading = heading_between(path[-2], path[-1])
            pose.x, pose.y = target_node.x, target_node.y
            executed_path.extend(path[1:])
            timeline.append(
                {
                    "step": index,
                    "action": "go_to_goal",
                    "detail": f"A* route to {target.label}",
                    "path_length": len(path) - 1,
                    "end_pose": pose_dict(pose),
                }
            )
            continue

        if action_name == "rotate":
            params = action.get("params", {})
            angle = float(params.get("angle", 0))
            direction = 1 if params.get("is_clockwise") else -1
            pose.heading = normalize_heading(pose.heading + direction * angle)
            timeline.append(
                {
                    "step": index,
                    "action": "rotate",
                    "detail": f"heading -> {pose.heading:.0f} deg",
                    "end_pose": pose_dict(pose),
                }
            )
            continue

        if action_name == "move":
            params = action.get("params", {})
            distance = _move_distance(params)
            signed_distance = distance if params.get("is_forward", True) else -distance
            path, stopped = project_move(pose, signed_distance, map_data)
            if stopped:
                warnings.append("A move command stopped at an unavailable map edge.")
            if len(path) > 1:
                pose.heading = heading_between(path[-2], path[-1])
                pose.x, pose.y = path[-1]["x"], path[-1]["y"]
                executed_path.extend(path[1:])
            timeline.append(
                {
                    "step": index,
                    "action": "move",
                    "detail": f"moved {max(0, len(path) - 1)} cells",
                    "end_pose": pose_dict(pose),
                }
            )
            continue

        raise ValueError(f'Unsupported internal action "{action_name}".')

    return {
        "timeline": timeline,
        "path": executed_path,
        "final_pose": pose_dict(pose),
        "warnings": warnings,
        "svg": render_svg(executed_path, pose, map_data),
    }


def build_runtime_frames(
    command: dict[str, Any], *, repository: MapRepository, start: str = "A"
) -> list[dict[str, Any]]:
    map_data = repository.load()
    start_node, start_label = require_start_node(map_data, start)
    pose = Pose(x=start_node.x, y=start_node.y, heading=0.0)
    path_so_far = [{"x": pose.x, "y": pose.y}]
    frames = [
        runtime_frame(
            pose=pose,
            path=path_so_far,
            step=0,
            action="start",
            detail=f"Start at {start_label}",
            map_data=map_data,
        )
    ]

    for index, action in enumerate(flatten_actions(command), start=1):
        action_name = action.get("action")
        if action_name == "stop":
            frames.append(
                runtime_frame(
                    pose=pose,
                    path=path_so_far,
                    step=index,
                    action="stop",
                    detail="Execution stopped",
                    map_data=map_data,
                )
            )
            break

        if action_name == "go_to_goal":
            value = action.get("params", {}).get("location", {}).get("value")
            target = require_location(map_data, value)
            target_node = map_data.nodes[target.node_id]
            path = astar(
                {"x": pose.x, "y": pose.y},
                {"x": target_node.x, "y": target_node.y},
                map_data,
            )
            if not path:
                raise ValueError(f'No A* path from ({pose.x}, {pose.y}) to "{target.name}".')
            if len(path) == 1:
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="go_to_goal",
                        detail=f"Already at {target.label}",
                        map_data=map_data,
                    )
                )
                continue
            for path_index, current in enumerate(path[1:], start=1):
                previous = path[path_index - 1]
                pose.heading = heading_between(previous, current)
                pose.x, pose.y = current["x"], current["y"]
                path_so_far.append({"x": pose.x, "y": pose.y})
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="go_to_goal",
                        detail=f"A* to {target.label} ({path_index}/{len(path) - 1})",
                        map_data=map_data,
                    )
                )
            continue

        if action_name == "rotate":
            params = action.get("params", {})
            angle = float(params.get("angle", 0))
            direction = 1 if params.get("is_clockwise") else -1
            start_heading = pose.heading
            tick_count = max(1, min(12, round(angle / 15)))
            for tick in range(1, tick_count + 1):
                pose.heading = normalize_heading(start_heading + direction * angle * tick / tick_count)
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="rotate",
                        detail=f"Rotate to {pose.heading:.0f} deg",
                        map_data=map_data,
                    )
                )
            continue

        if action_name == "move":
            params = action.get("params", {})
            distance = _move_distance(params)
            signed_distance = distance if params.get("is_forward", True) else -distance
            path, stopped = project_move(pose, signed_distance, map_data)
            if len(path) == 1:
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="move",
                        detail="Move blocked" if stopped else "Move produced no displacement",
                        map_data=map_data,
                    )
                )
                continue
            for path_index, current in enumerate(path[1:], start=1):
                previous = path[path_index - 1]
                pose.heading = heading_between(previous, current)
                pose.x, pose.y = current["x"], current["y"]
                path_so_far.append({"x": pose.x, "y": pose.y})
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="move",
                        detail=f"Move ({path_index}/{len(path) - 1})",
                        map_data=map_data,
                    )
                )
            if stopped:
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="move",
                        detail="Move stopped at unavailable edge",
                        map_data=map_data,
                    )
                )
            continue

        raise ValueError(f'Unsupported internal action "{action_name}".')
    return frames


def runtime_frame(
    *,
    pose: Pose,
    path: list[dict[str, int]],
    step: int,
    action: str,
    detail: str,
    map_data: MapData,
) -> dict[str, Any]:
    return {
        "step": step,
        "action": action,
        "detail": detail,
        "pose": pose_dict(pose),
        "path": list(path),
        "svg": render_svg(path, pose, map_data),
    }


def flatten_actions(command: dict[str, Any]) -> list[dict[str, Any]]:
    if command.get("action") == "sequence":
        params = command.get("params", [])
        if not isinstance(params, list):
            raise ValueError("sequence.params must be a list")
        flattened: list[dict[str, Any]] = []
        for item in params:
            flattened.extend(flatten_actions(item))
        return flattened
    return [command]


def astar(
    start: dict[str, int], goal: dict[str, int], map_data: MapData
) -> list[dict[str, int]]:
    start_key = (start["x"], start["y"])
    goal_key = (goal["x"], goal["y"])
    if not map_data.node_at(start_key) or not map_data.node_at(goal_key):
        return []
    frontier: list[tuple[int, int, tuple[int, int]]] = []
    heappush(frontier, (0, 0, start_key))
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start_key: None}
    cost_so_far = {start_key: 0}
    counter = 0
    while frontier:
        _, _, current = heappop(frontier)
        if current == goal_key:
            return reconstruct_path(came_from, current)
        for next_cell in map_data.neighbors(current):
            new_cost = cost_so_far[current] + 1
            if next_cell not in cost_so_far or new_cost < cost_so_far[next_cell]:
                cost_so_far[next_cell] = new_cost
                counter += 1
                priority = new_cost + manhattan(next_cell, goal_key)
                heappush(frontier, (priority, counter, next_cell))
                came_from[next_cell] = current
    return []


def project_move(
    pose: Pose, signed_distance: float, map_data: MapData
) -> tuple[list[dict[str, int]], bool]:
    steps = max(0, round(abs(signed_distance)))
    dx, dy = heading_vector(pose.heading if signed_distance >= 0 else pose.heading + 180)
    path = [{"x": pose.x, "y": pose.y}]
    current = (pose.x, pose.y)
    stopped = False
    for _ in range(steps):
        next_cell = (current[0] + dx, current[1] + dy)
        if not map_data.can_traverse(current, next_cell):
            stopped = True
            break
        path.append({"x": next_cell[0], "y": next_cell[1]})
        current = next_cell
    return path, stopped


def render_svg(path: list[dict[str, int]], pose: Pose, map_data: MapData) -> str:
    width, height = map_data.width * CELL_SIZE, map_data.height * CELL_SIZE
    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for x in range(map_data.width + 1):
        parts.append(f'<path d="M{x * CELL_SIZE} 0 V{height}" stroke="#e5ebf0" stroke-width="1"/>')
    for y in range(map_data.height + 1):
        parts.append(f'<path d="M0 {y * CELL_SIZE} H{width}" stroke="#e5ebf0" stroke-width="1"/>')
    for y in range(map_data.height):
        for x in range(map_data.width):
            if not map_data.node_at((x, y)):
                parts.append(
                    f'<rect x="{x * CELL_SIZE + 4}" y="{y * CELL_SIZE + 4}" '
                    f'width="{CELL_SIZE - 8}" height="{CELL_SIZE - 8}" rx="4" fill="#2f3945"/>'
                )
    if len(path) > 1:
        points = " ".join(
            f'{cell_center(point)["x"]},{cell_center(point)["y"]}' for point in path
        )
        parts.append(f'<polyline points="{points}" fill="none" stroke="#2474c6" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>')
    for location in map_data.locations.values():
        node = map_data.nodes[location.node_id]
        center = cell_center({"x": node.x, "y": node.y})
        label = html.escape(location.label)
        parts.append(f'<circle cx="{center["x"]}" cy="{center["y"]}" r="12" fill="{html.escape(location.color)}"/>')
        parts.append(f'<text x="{center["x"]}" y="{center["y"] + 4}" fill="#fff" font-size="10" font-weight="700" text-anchor="middle">{label}</text>')
    car = cell_center({"x": pose.x, "y": pose.y})
    parts.append(
        f'<g transform="translate({car["x"]} {car["y"]}) rotate({pose.heading})">'
        '<path d="M16 0 L-12 -10 L-7 0 L-12 10 Z" fill="#0f766e" stroke="#063f3b" stroke-width="2"/>'
        '<rect x="-4" y="-5" width="8" height="10" fill="#e0f2fe"/></g>'
    )
    parts.append("</svg>")
    return "".join(parts)


def require_location(map_data: MapData, value: Any) -> MapLocationData:
    location = map_data.resolve_location(value)
    if location:
        return location
    known = ", ".join(sorted(item.name for item in map_data.locations.values()))
    raise ValueError(f'Unknown or ambiguous location "{value}". Known locations: {known}')


def require_start_node(map_data: MapData, value: Any) -> tuple[MapNodeData, str]:
    if isinstance(value, str) and value in map_data.nodes:
        return map_data.nodes[value], value
    location = require_location(map_data, value)
    return map_data.nodes[location.node_id], location.label


def reconstruct_path(
    came_from: dict[tuple[int, int], tuple[int, int] | None], current: tuple[int, int]
) -> list[dict[str, int]]:
    path = []
    while current is not None:
        path.append({"x": current[0], "y": current[1]})
        current = came_from[current]
    path.reverse()
    return path


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def heading_between(start: dict[str, int], end: dict[str, int]) -> float:
    dx, dy = end["x"] - start["x"], end["y"] - start["y"]
    if dx > 0:
        return 0.0
    if dy > 0:
        return 90.0
    if dx < 0:
        return 180.0
    if dy < 0:
        return 270.0
    return 0.0


def heading_vector(heading: float) -> tuple[int, int]:
    normalized = normalize_heading(heading)
    if 45 <= normalized < 135:
        return 0, 1
    if 135 <= normalized < 225:
        return -1, 0
    if 225 <= normalized < 315:
        return 0, -1
    return 1, 0


def normalize_heading(value: float) -> float:
    return value % 360


def _move_distance(params: dict[str, Any]) -> float:
    if "distance" in params:
        return float(params["distance"])
    return float(params.get("linear_speed", 0)) * float(params.get("duration", 0))


def cell_center(cell: dict[str, int]) -> dict[str, float]:
    return {
        "x": cell["x"] * CELL_SIZE + CELL_SIZE / 2,
        "y": cell["y"] * CELL_SIZE + CELL_SIZE / 2,
    }


def pose_dict(pose: Pose) -> dict[str, Any]:
    return {"x": pose.x, "y": pose.y, "heading": round(pose.heading, 2)}


def pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
