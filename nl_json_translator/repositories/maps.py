from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from nl_json_translator.domain.location_text import normalize_location_text
from nl_json_translator.infrastructure.orm_models import LocationRecord, MapEdgeRecord, MapNodeRecord


@dataclass(frozen=True)
class MapNodeData:
    id: str
    x: int
    y: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class MapEdgeData:
    id: str
    from_node_id: str
    to_node_id: str
    distance: float
    travel_time: float
    capacity: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class MapLocationData:
    id: str
    name: str
    node_id: str
    label: str
    color: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class MapData:
    nodes: dict[str, MapNodeData]
    adjacency: dict[str, tuple[str, ...]]
    locations: dict[str, MapLocationData]
    edges: dict[str, MapEdgeData]

    def __post_init__(self) -> None:
        coordinate_index = {(node.x, node.y): node_id for node_id, node in self.nodes.items()}
        outgoing_edges: dict[str, list[MapEdgeData]] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges.values():
            if edge.from_node_id in outgoing_edges and edge.to_node_id in self.nodes:
                outgoing_edges[edge.from_node_id].append(edge)
        object.__setattr__(self, "_coordinate_index", coordinate_index)
        object.__setattr__(
            self,
            "_outgoing_edges",
            {node_id: tuple(items) for node_id, items in outgoing_edges.items()},
        )

    @property
    def width(self) -> int:
        return max((node.x for node in self.nodes.values()), default=-1) + 1

    @property
    def height(self) -> int:
        return max((node.y for node in self.nodes.values()), default=-1) + 1

    def node_at(self, coordinate: tuple[int, int]) -> Optional[MapNodeData]:
        node_id = self._coordinate_index.get(coordinate)  # type: ignore[attr-defined]
        return self.nodes.get(node_id) if node_id else None

    def neighbors(self, coordinate: tuple[int, int]) -> Iterable[tuple[int, int]]:
        node = self.node_at(coordinate)
        if not node:
            return ()
        return (
            (self.nodes[next_id].x, self.nodes[next_id].y)
            for next_id in self.adjacency.get(node.id, ())
            if next_id in self.nodes
        )

    def can_traverse(self, start: tuple[int, int], end: tuple[int, int]) -> bool:
        start_node = self.node_at(start)
        end_node = self.node_at(end)
        return bool(start_node and end_node and end_node.id in self.adjacency.get(start_node.id, ()))

    def outgoing_edges(self, node_id: str) -> tuple[MapEdgeData, ...]:
        return self._outgoing_edges.get(node_id, ())  # type: ignore[attr-defined]

    def resolve_location(self, value: Any) -> Optional[MapLocationData]:
        if not isinstance(value, str):
            return None
        if value in self.locations:
            return self.locations[value]
        normalized = normalize_location_text(value)
        matches = [
            location
            for location in self.locations.values()
            if normalize_location_text(location.name) == normalized
            or any(normalize_location_text(alias) == normalized for alias in location.aliases)
        ]
        return matches[0] if len(matches) == 1 else None


class MapRepository:
    def __init__(self, session: Session):
        self.session = session

    def load(self) -> MapData:
        node_records = list(self.session.scalars(select(MapNodeRecord).where(MapNodeRecord.enabled.is_(True)).order_by(MapNodeRecord.id)))
        nodes = {
            record.id: MapNodeData(record.id, record.x, record.y, dict(record.metadata_json))
            for record in node_records
        }
        adjacency_lists: dict[str, list[str]] = {node_id: [] for node_id in nodes}
        edge_records = list(
            self.session.scalars(
                select(MapEdgeRecord)
                .where(MapEdgeRecord.enabled.is_(True))
                .order_by(MapEdgeRecord.id)
            )
        )
        edges = {
            edge.id: MapEdgeData(
                id=edge.id,
                from_node_id=edge.from_node_id,
                to_node_id=edge.to_node_id,
                distance=edge.distance,
                travel_time=edge.travel_time,
                capacity=edge.capacity,
                metadata=dict(edge.metadata_json),
            )
            for edge in edge_records
            if edge.from_node_id in nodes and edge.to_node_id in nodes
        }
        for edge in edges.values():
            if edge.from_node_id in nodes and edge.to_node_id in nodes:
                adjacency_lists[edge.from_node_id].append(edge.to_node_id)
        adjacency = {node_id: tuple(neighbor_ids) for node_id, neighbor_ids in adjacency_lists.items()}

        location_records = self.session.scalars(
            select(LocationRecord)
            .options(selectinload(LocationRecord.aliases))
            .where(LocationRecord.enabled.is_(True))
            .order_by(LocationRecord.id)
        )
        locations = {}
        for record in location_records:
            if record.map_node_id not in nodes:
                continue
            metadata = record.metadata_json
            locations[record.id] = MapLocationData(
                id=record.id,
                name=record.name,
                node_id=record.map_node_id,
                label=str(metadata.get("label", record.name)),
                color=str(metadata.get("color", "#475569")),
                aliases=tuple(alias.alias for alias in record.aliases),
            )
        return MapData(nodes=nodes, adjacency=adjacency, locations=locations, edges=edges)
