from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from nl_json_translator.infrastructure.orm_models import LocationRecord


@dataclass(frozen=True)
class LocationData:
    id: str
    name: str
    location_type: str
    map_node_id: str
    enabled: bool
    metadata: dict[str, Any]
    aliases: tuple[str, ...]


class LocationRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, location_id: str) -> Optional[LocationData]:
        statement = (
            select(LocationRecord)
            .options(selectinload(LocationRecord.aliases))
            .where(LocationRecord.id == location_id)
        )
        record = self.session.scalar(statement)
        return _to_data(record) if record else None

    def list_enabled(self) -> list[LocationData]:
        statement = (
            select(LocationRecord)
            .options(selectinload(LocationRecord.aliases))
            .where(LocationRecord.enabled.is_(True))
            .order_by(LocationRecord.name, LocationRecord.id)
        )
        return [_to_data(record) for record in self.session.scalars(statement)]


def _to_data(record: LocationRecord) -> LocationData:
    return LocationData(
        id=record.id,
        name=record.name,
        location_type=record.location_type,
        map_node_id=record.map_node_id,
        enabled=record.enabled,
        metadata=dict(record.metadata_json),
        aliases=tuple(alias.alias for alias in record.aliases),
    )
