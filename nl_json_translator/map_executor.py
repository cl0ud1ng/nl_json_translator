from __future__ import annotations

import html
import json
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Any, Iterable


GRID_WIDTH = 20
GRID_HEIGHT = 14
CELL_SIZE = 34

POINTS: dict[str, dict[str, Any]] = {
    "A": {"x": 2, "y": 2, "label": "A", "color": "#dc2626"},
    "B": {"x": 16, "y": 3, "label": "B", "color": "#2563eb"},
    "C": {"x": 6, "y": 11, "label": "C", "color": "#7c3aed"},
    "lab": {"x": 17, "y": 11, "label": "Lab", "color": "#0891b2"},
    "charging station": {"x": 1, "y": 11, "label": "Charge", "color": "#ca8a04"},
}

OBSTACLES = [
    *({"x": x, "y": 5} for x in range(4, 11)),
    *({"x": x, "y": 9} for x in range(8, 13)),
    *({"x": 12, "y": y} for y in range(2, 7)),
    *({"x": 15, "y": y} for y in range(8, 13)),
    {"x": 5, "y": 1},
    {"x": 5, "y": 2},
    {"x": 5, "y": 3},
    {"x": 6, "y": 8},
    {"x": 7, "y": 8},
    {"x": 12, "y": 12},
    {"x": 13, "y": 12},
]

OBSTACLE_KEYS = {(item["x"], item["y"]) for item in OBSTACLES}


@dataclass
class Pose:
    x: int
    y: int
    heading: float = 0.0


def execute_command(command: dict[str, Any], *, start: str = "A") -> dict[str, Any]:
    start_point = resolve_point(start) or POINTS["A"]
    pose = Pose(x=start_point["x"], y=start_point["y"], heading=0.0)
    actions = flatten_actions(command)
    timeline: list[dict[str, Any]] = []
    executed_path = [{"x": pose.x, "y": pose.y}]
    warnings: list[str] = []

    for index, action in enumerate(actions, start=1):
        action_name = action.get("action")
        if action_name == "stop":
            timeline.append({"step": index, "action": "stop", "detail": "Execution stopped"})
            break

        if action_name == "go_to_goal":
            location = action.get("params", {}).get("location", {}).get("value")
            target = resolve_point(location)
            if not target:
                raise ValueError(f'Unknown location "{location}". Known points: {", ".join(POINTS)}')
            path = astar({"x": pose.x, "y": pose.y}, target)
            if not path:
                raise ValueError(f'No A* path from ({pose.x}, {pose.y}) to "{location}".')
            if len(path) > 1:
                pose.heading = heading_between(path[-2], path[-1])
            pose.x = target["x"]
            pose.y = target["y"]
            executed_path.extend(path[1:])
            timeline.append(
                {
                    "step": index,
                    "action": "go_to_goal",
                    "detail": f'A* route to {target["label"]}',
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
            if "distance" in params:
                distance = float(params["distance"])
            else:
                distance = float(params.get("linear_speed", 0)) * float(params.get("duration", 0))
            signed_distance = distance if params.get("is_forward", True) else -distance
            path, stopped = project_move(pose, signed_distance)
            if stopped:
                warnings.append("A move command stopped at an obstacle or map boundary.")
            if len(path) > 1:
                pose.heading = heading_between(path[-2], path[-1])
                pose.x = path[-1]["x"]
                pose.y = path[-1]["y"]
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

        raise ValueError(f'Unsupported action "{action_name}".')

    return {
        "timeline": timeline,
        "path": executed_path,
        "final_pose": pose_dict(pose),
        "warnings": warnings,
        "svg": render_svg(executed_path, pose),
    }


def build_runtime_frames(command: dict[str, Any], *, start: str = "A") -> list[dict[str, Any]]:
    start_point = resolve_point(start) or POINTS["A"]
    pose = Pose(x=start_point["x"], y=start_point["y"], heading=0.0)
    actions = flatten_actions(command)
    path_so_far = [{"x": pose.x, "y": pose.y}]
    frames: list[dict[str, Any]] = [
        runtime_frame(
            pose=pose,
            path=path_so_far,
            step=0,
            action="start",
            detail=f'Start at {start_point["label"]}',
        )
    ]

    for index, action in enumerate(actions, start=1):
        action_name = action.get("action")
        if action_name == "stop":
            frames.append(
                runtime_frame(
                    pose=pose,
                    path=path_so_far,
                    step=index,
                    action="stop",
                    detail="Execution stopped",
                )
            )
            break

        if action_name == "go_to_goal":
            location = action.get("params", {}).get("location", {}).get("value")
            target = resolve_point(location)
            if not target:
                raise ValueError(f'Unknown location "{location}". Known points: {", ".join(POINTS)}')
            path = astar({"x": pose.x, "y": pose.y}, target)
            if not path:
                raise ValueError(f'No A* path from ({pose.x}, {pose.y}) to "{location}".')
            if len(path) == 1:
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="go_to_goal",
                        detail=f'Already at {target["label"]}',
                    )
                )
                continue
            for path_index in range(1, len(path)):
                previous = path[path_index - 1]
                current = path[path_index]
                pose.heading = heading_between(previous, current)
                pose.x = current["x"]
                pose.y = current["y"]
                path_so_far.append({"x": pose.x, "y": pose.y})
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="go_to_goal",
                        detail=f'A* to {target["label"]} ({path_index}/{len(path) - 1})',
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
                    )
                )
            continue

        if action_name == "move":
            params = action.get("params", {})
            if "distance" in params:
                distance = float(params["distance"])
            else:
                distance = float(params.get("linear_speed", 0)) * float(params.get("duration", 0))
            signed_distance = distance if params.get("is_forward", True) else -distance
            path, stopped = project_move(pose, signed_distance)
            if len(path) == 1:
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="move",
                        detail="Move blocked" if stopped else "Move produced no displacement",
                    )
                )
                continue
            for path_index in range(1, len(path)):
                previous = path[path_index - 1]
                current = path[path_index]
                pose.heading = heading_between(previous, current)
                pose.x = current["x"]
                pose.y = current["y"]
                path_so_far.append({"x": pose.x, "y": pose.y})
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="move",
                        detail=f"Move ({path_index}/{len(path) - 1})",
                    )
                )
            if stopped:
                frames.append(
                    runtime_frame(
                        pose=pose,
                        path=path_so_far,
                        step=index,
                        action="move",
                        detail="Move stopped at obstacle or boundary",
                    )
                )
            continue

        raise ValueError(f'Unsupported action "{action_name}".')

    return frames


def runtime_frame(
    *,
    pose: Pose,
    path: list[dict[str, int]],
    step: int,
    action: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "step": step,
        "action": action,
        "detail": detail,
        "pose": pose_dict(pose),
        "path": list(path),
        "svg": render_svg(path, pose),
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


def astar(start: dict[str, int], goal: dict[str, Any]) -> list[dict[str, int]]:
    start_key = (start["x"], start["y"])
    goal_key = (goal["x"], goal["y"])
    frontier: list[tuple[int, int, tuple[int, int]]] = []
    heappush(frontier, (0, 0, start_key))
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start_key: None}
    cost_so_far: dict[tuple[int, int], int] = {start_key: 0}
    counter = 0

    while frontier:
        _, _, current = heappop(frontier)
        if current == goal_key:
            return reconstruct_path(came_from, current)
        for next_cell in neighbors(current):
            new_cost = cost_so_far[current] + 1
            if next_cell not in cost_so_far or new_cost < cost_so_far[next_cell]:
                cost_so_far[next_cell] = new_cost
                priority = new_cost + manhattan(next_cell, goal_key)
                counter += 1
                heappush(frontier, (priority, counter, next_cell))
                came_from[next_cell] = current
    return []


def project_move(pose: Pose, signed_distance: float) -> tuple[list[dict[str, int]], bool]:
    steps = max(0, round(abs(signed_distance)))
    dx, dy = heading_vector(pose.heading if signed_distance >= 0 else pose.heading + 180)
    path = [{"x": pose.x, "y": pose.y}]
    current = (pose.x, pose.y)
    stopped = False
    for _ in range(steps):
        next_cell = (current[0] + dx, current[1] + dy)
        if not in_bounds(next_cell) or next_cell in OBSTACLE_KEYS:
            stopped = True
            break
        path.append({"x": next_cell[0], "y": next_cell[1]})
        current = next_cell
    return path, stopped


def render_svg(path: list[dict[str, int]], pose: Pose) -> str:
    width = GRID_WIDTH * CELL_SIZE
    height = GRID_HEIGHT * CELL_SIZE
    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for x in range(GRID_WIDTH + 1):
        parts.append(f'<path d="M{x * CELL_SIZE} 0 V{height}" stroke="#e5ebf0" stroke-width="1"/>')
    for y in range(GRID_HEIGHT + 1):
        parts.append(f'<path d="M0 {y * CELL_SIZE} H{width}" stroke="#e5ebf0" stroke-width="1"/>')
    for obstacle in OBSTACLES:
        x = obstacle["x"] * CELL_SIZE + 4
        y = obstacle["y"] * CELL_SIZE + 4
        size = CELL_SIZE - 8
        parts.append(f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="4" fill="#2f3945"/>')
    if len(path) > 1:
        points = " ".join(f'{cell_center(p)["x"]},{cell_center(p)["y"]}' for p in path)
        parts.append(f'<polyline points="{points}" fill="none" stroke="#2474c6" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>')
    for point in POINTS.values():
        center = cell_center(point)
        label = html.escape(point["label"])
        parts.append(f'<circle cx="{center["x"]}" cy="{center["y"]}" r="12" fill="{point["color"]}"/>')
        parts.append(f'<text x="{center["x"]}" y="{center["y"] + 4}" fill="#fff" font-size="10" font-weight="700" text-anchor="middle">{label}</text>')
    car = cell_center({"x": pose.x, "y": pose.y})
    parts.append(
        f'<g transform="translate({car["x"]} {car["y"]}) rotate({pose.heading})">'
        '<path d="M16 0 L-12 -10 L-7 0 L-12 10 Z" fill="#0f766e" stroke="#063f3b" stroke-width="2"/>'
        '<rect x="-4" y="-5" width="8" height="10" fill="#e0f2fe"/>'
        "</g>"
    )
    parts.append("</svg>")
    return "".join(parts)


def resolve_point(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    if value in POINTS:
        return POINTS[value]
    lower = value.lower().strip()
    for name, point in POINTS.items():
        if name.lower() == lower:
            return point
    return None


def reconstruct_path(came_from: dict[tuple[int, int], tuple[int, int] | None], current: tuple[int, int]) -> list[dict[str, int]]:
    path = []
    while current is not None:
        path.append({"x": current[0], "y": current[1]})
        current = came_from[current]
    path.reverse()
    return path


def neighbors(cell: tuple[int, int]) -> Iterable[tuple[int, int]]:
    x, y = cell
    for next_cell in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if in_bounds(next_cell) and next_cell not in OBSTACLE_KEYS:
            yield next_cell


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def heading_between(start: dict[str, int], end: dict[str, int]) -> float:
    dx = end["x"] - start["x"]
    dy = end["y"] - start["y"]
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


def in_bounds(cell: tuple[int, int]) -> bool:
    return 0 <= cell[0] < GRID_WIDTH and 0 <= cell[1] < GRID_HEIGHT


def cell_center(cell: dict[str, int]) -> dict[str, float]:
    return {"x": cell["x"] * CELL_SIZE + CELL_SIZE / 2, "y": cell["y"] * CELL_SIZE + CELL_SIZE / 2}


def pose_dict(pose: Pose) -> dict[str, Any]:
    return {"x": pose.x, "y": pose.y, "heading": round(pose.heading, 2)}


def pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
