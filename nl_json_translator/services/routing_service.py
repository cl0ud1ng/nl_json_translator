from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from typing import Optional

from nl_json_translator.repositories.maps import MapData


@dataclass(frozen=True)
class RoutePlan:
    node_ids: tuple[str, ...]
    distance: float
    travel_time: float


class RoutingService:
    """Deterministic shortest-path planning over directed, weighted map edges."""

    def shortest_route(
        self, map_data: MapData, start_node_id: str, goal_node_id: str
    ) -> Optional[RoutePlan]:
        if start_node_id not in map_data.nodes or goal_node_id not in map_data.nodes:
            return None
        if start_node_id == goal_node_id:
            return RoutePlan((start_node_id,), 0.0, 0.0)

        sequence = count()
        frontier: list[tuple[float, int, str]] = [(0.0, next(sequence), start_node_id)]
        distances = {start_node_id: 0.0}
        travel_times = {start_node_id: 0.0}
        previous: dict[str, Optional[str]] = {start_node_id: None}

        while frontier:
            distance, _, node_id = heappop(frontier)
            if distance > distances[node_id]:
                continue
            if node_id == goal_node_id:
                node_ids = _reconstruct(previous, goal_node_id)
                return RoutePlan(
                    node_ids=node_ids,
                    distance=round(distances[goal_node_id], 6),
                    travel_time=round(travel_times[goal_node_id], 6),
                )
            for edge in map_data.outgoing_edges(node_id):
                new_distance = distance + edge.distance
                if new_distance >= distances.get(edge.to_node_id, float("inf")):
                    continue
                distances[edge.to_node_id] = new_distance
                travel_times[edge.to_node_id] = travel_times[node_id] + edge.travel_time
                previous[edge.to_node_id] = node_id
                heappush(frontier, (new_distance, next(sequence), edge.to_node_id))
        return None


def _reconstruct(previous: dict[str, Optional[str]], current: str) -> tuple[str, ...]:
    path = []
    while current is not None:
        path.append(current)
        current = previous[current]  # type: ignore[assignment]
    path.reverse()
    return tuple(path)
