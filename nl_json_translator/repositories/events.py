from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import AgentEventType
from nl_json_translator.infrastructure.orm_models import AgentEventRecord


@dataclass(frozen=True)
class AgentEventData:
    id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    order_id: Optional[str]
    mission_id: Optional[str]
    vehicle_id: Optional[str]
    payload: dict[str, Any]
    occurred_at: datetime


class EventRepository:
    def __init__(self, session: Session):
        self.session = session

    def append(
        self,
        *,
        event_type: AgentEventType | str,
        aggregate_type: str,
        aggregate_id: str,
        order_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        vehicle_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> AgentEventData:
        record = AgentEventRecord(
            id=f"event_{uuid4().hex}",
            event_type=(event_type.value if isinstance(event_type, AgentEventType) else event_type),
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            order_id=order_id,
            mission_id=mission_id,
            vehicle_id=vehicle_id,
            payload_json=dict(payload or {}),
        )
        self.session.add(record)
        self.session.flush()
        return _to_data(record)

    def list_for_mission(self, mission_id: str) -> list[AgentEventData]:
        statement = (
            select(AgentEventRecord)
            .where(AgentEventRecord.mission_id == mission_id)
            .order_by(AgentEventRecord.occurred_at, AgentEventRecord.id)
        )
        return [_to_data(record) for record in self.session.scalars(statement)]

    def list_recent(self, *, limit: int = 50) -> list[AgentEventData]:
        if limit <= 0:
            return []
        statement = (
            select(AgentEventRecord)
            .order_by(AgentEventRecord.occurred_at.desc(), AgentEventRecord.id.desc())
            .limit(limit)
        )
        return [_to_data(record) for record in self.session.scalars(statement)]


def _to_data(record: AgentEventRecord) -> AgentEventData:
    return AgentEventData(
        id=record.id,
        event_type=record.event_type,
        aggregate_type=record.aggregate_type,
        aggregate_id=record.aggregate_id,
        order_id=record.order_id,
        mission_id=record.mission_id,
        vehicle_id=record.vehicle_id,
        payload=dict(record.payload_json),
        occurred_at=record.occurred_at,
    )
