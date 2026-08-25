from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import AgentCommandStatus, AgentCommandType
from nl_json_translator.infrastructure.orm_models import AgentCommandRecord


@dataclass(frozen=True)
class AgentCommandData:
    id: str
    target_agent_id: str
    command_type: AgentCommandType
    status: AgentCommandStatus
    vehicle_id: Optional[str]
    mission_id: Optional[str]
    correlation_id: Optional[str]
    payload: dict[str, Any]


class CommandRepository:
    def __init__(self, session: Session):
        self.session = session

    def enqueue(
        self,
        *,
        target_agent_id: str,
        command_type: AgentCommandType,
        idempotency_key: str,
        payload: dict[str, Any],
        vehicle_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> AgentCommandData:
        existing = self.session.scalar(
            select(AgentCommandRecord).where(
                AgentCommandRecord.idempotency_key == idempotency_key
            )
        )
        if existing:
            return _to_data(existing)
        record = AgentCommandRecord(
            id=f"command_{uuid4().hex}",
            target_agent_id=target_agent_id,
            command_type=command_type.value,
            status=AgentCommandStatus.PENDING.value,
            vehicle_id=vehicle_id,
            mission_id=mission_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_json=dict(payload),
        )
        self.session.add(record)
        self.session.flush()
        return _to_data(record)

    def next_for_agent(self, agent_id: str) -> Optional[AgentCommandData]:
        statement = (
            select(AgentCommandRecord)
            .where(
                AgentCommandRecord.target_agent_id == agent_id,
                AgentCommandRecord.status.in_(
                    [AgentCommandStatus.RUNNING.value, AgentCommandStatus.PENDING.value]
                ),
            )
            .order_by(AgentCommandRecord.created_at, AgentCommandRecord.id)
        )
        record = self.session.scalar(statement)
        return _to_data(record) if record else None

    def start(self, command_id: str) -> bool:
        record = self.session.get(AgentCommandRecord, command_id)
        if not record:
            return False
        if record.status == AgentCommandStatus.PENDING.value:
            record.status = AgentCommandStatus.RUNNING.value
            record.started_at = datetime.now(timezone.utc)
            self.session.flush()
        return record.status == AgentCommandStatus.RUNNING.value

    def complete(self, command_id: str) -> bool:
        record = self.session.get(AgentCommandRecord, command_id)
        if not record:
            return False
        record.status = AgentCommandStatus.COMPLETED.value
        record.completed_at = datetime.now(timezone.utc)
        self.session.flush()
        return True


def _to_data(record: AgentCommandRecord) -> AgentCommandData:
    return AgentCommandData(
        id=record.id,
        target_agent_id=record.target_agent_id,
        command_type=AgentCommandType(record.command_type),
        status=AgentCommandStatus(record.status),
        vehicle_id=record.vehicle_id,
        mission_id=record.mission_id,
        correlation_id=record.correlation_id,
        payload=dict(record.payload_json),
    )
