from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from typing import Optional

from nl_json_translator.repositories.maps import MapData


class CooperativePlanningError(RuntimeError):
    pass


@dataclass(frozen=True)
class TimedRoute:
    node_ids: tuple[str, ...]
    start_time: int

    @property
    def end_time(self) -> int:
        return self.start_time + len(self.node_ids) - 1

    @property
    def wait_count(self) -> int:
        return sum(
            current == previous
            for previous, current in zip(self.node_ids, self.node_ids[1:])
        )


class ReservationTable:
    """Discrete node/edge reservations used by prioritized cooperative planning."""

    def __init__(self, map_data: MapData, *, service_node_capacity: int = 2):
        self.map_data = map_data
        self.service_nodes = {
            location.node_id for location in map_data.locations.values()
        }
        self.service_node_capacity = service_node_capacity
        self.node_slots: dict[tuple[str, int], int] = defaultdict(int)
        self.edge_slots: set[tuple[str, str, int]] = set()

    def node_capacity(self, node_id: str) -> int:
        return self.service_node_capacity if node_id in self.service_nodes else 1

    def can_occupy(self, node_id: str, time_slot: int) -> bool:
        return self.node_slots[(node_id, time_slot)] < self.node_capacity(node_id)

    def can_traverse(self, start_id: str, end_id: str, time_slot: int) -> bool:
        if start_id == end_id:
            return True
        return _edge_key(start_id, end_id, time_slot) not in self.edge_slots

    def reserve_timeline(self, node_ids: tuple[str, ...], *, start_time: int = 0) -> None:
        for offset, node_id in enumerate(node_ids):
            self.node_slots[(node_id, start_time + offset)] += 1
            if offset == len(node_ids) - 1:
                continue
            next_id = node_ids[offset + 1]
            if node_id != next_id:
                self.edge_slots.add(_edge_key(node_id, next_id, start_time + offset))


class CooperativeRoutingService:
    def plan(
        self,
        map_data: MapData,
        reservations: ReservationTable,
        *,
        start_node_id: str,
        goal_node_id: str,
        start_time: int,
        goal_hold_steps: int = 0,
        max_steps: int = 320,
    ) -> TimedRoute:
        if start_node_id not in map_data.nodes or goal_node_id not in map_data.nodes:
            raise CooperativePlanningError("route endpoint is not an enabled map node")
        if not reservations.can_occupy(start_node_id, start_time):
            raise CooperativePlanningError(
                f'node "{start_node_id}" is occupied at time {start_time}'
            )

        sequence = count()
        start_state = (start_node_id, start_time)
        frontier: list[tuple[int, int, int, str, int]] = [
            (
                _heuristic(map_data, start_node_id, goal_node_id),
                0,
                next(sequence),
                start_node_id,
                start_time,
            )
        ]
        previous: dict[tuple[str, int], Optional[tuple[str, int]]] = {start_state: None}
        best_time: dict[tuple[str, int], int] = {start_state: 0}
        deadline = start_time + max_steps

        while frontier:
            _, cost, _, node_id, time_slot = heappop(frontier)
            state = (node_id, time_slot)
            if cost != best_time.get(state):
                continue
            if node_id == goal_node_id and all(
                reservations.can_occupy(goal_node_id, time_slot + offset)
                for offset in range(1, goal_hold_steps + 1)
            ):
                return TimedRoute(_reconstruct(previous, state), start_time)
            if time_slot >= deadline:
                continue

            next_time = time_slot + 1
            candidates = [edge.to_node_id for edge in map_data.outgoing_edges(node_id)]
            candidates.sort()
            candidates.append(node_id)
            for next_id in candidates:
                if not reservations.can_occupy(next_id, next_time):
                    continue
                if not reservations.can_traverse(node_id, next_id, time_slot):
                    continue
                next_state = (next_id, next_time)
                next_cost = cost + 1
                if next_cost >= best_time.get(next_state, max_steps + 1):
                    continue
                best_time[next_state] = next_cost
                previous[next_state] = state
                estimate = next_cost + _heuristic(map_data, next_id, goal_node_id)
                heappush(
                    frontier,
                    (estimate, next_cost, next(sequence), next_id, next_time),
                )
        raise CooperativePlanningError(
            f'no conflict-free route from "{start_node_id}" to "{goal_node_id}"'
        )


def _edge_key(start_id: str, end_id: str, time_slot: int) -> tuple[str, str, int]:
    first, second = sorted((start_id, end_id))
    return first, second, time_slot


def _heuristic(map_data: MapData, node_id: str, goal_id: str) -> int:
    node = map_data.nodes[node_id]
    goal = map_data.nodes[goal_id]
    return abs(node.x - goal.x) + abs(node.y - goal.y)


def _reconstruct(
    previous: dict[tuple[str, int], Optional[tuple[str, int]]],
    current: tuple[str, int],
) -> tuple[str, ...]:
    path = []
    while current is not None:
        path.append(current[0])
        current = previous[current]  # type: ignore[assignment]
    path.reverse()
    return tuple(path)
