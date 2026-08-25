from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from nl_json_translator.domain.enums import (
    MissionStatus,
    MissionStepStatus,
    MissionStepType,
)
from nl_json_translator.infrastructure.orm_models import MissionRecord, MissionStepRecord


@dataclass(frozen=True)
class MissionStepDefinition:
    step_type: MissionStepType
    start_node_id: Optional[str] = None
    end_node_id: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MissionStepData:
    id: str
    sequence_no: int
    step_type: MissionStepType
    status: MissionStepStatus
    start_node_id: Optional[str]
    end_node_id: Optional[str]
    details: dict[str, Any]


@dataclass(frozen=True)
class MissionData:
    id: str
    order_id: str
    vehicle_id: str
    status: MissionStatus
    active: bool
    assigned_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    steps: tuple[MissionStepData, ...]


class MissionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        order_id: str,
        vehicle_id: str,
        steps: Sequence[MissionStepDefinition],
        mission_id: Optional[str] = None,
    ) -> MissionData:
        if not steps:
            raise ValueError("mission must contain at least one step")
        record = MissionRecord(
            id=mission_id or f"mission_{uuid4().hex}",
            order_id=order_id,
            vehicle_id=vehicle_id,
            status=MissionStatus.CREATED.value,
            active=True,
        )
        for sequence_no, definition in enumerate(steps, start=1):
            record.steps.append(
                MissionStepRecord(
                    id=f"step_{uuid4().hex}",
                    sequence_no=sequence_no,
                    step_type=definition.step_type.value,
                    status=MissionStepStatus.PENDING.value,
                    start_node_id=definition.start_node_id,
                    end_node_id=definition.end_node_id,
                    details_json=dict(definition.details),
                )
            )
        self.session.add(record)
        self.session.flush()
        return _to_data(record)

    def get(self, mission_id: str) -> Optional[MissionData]:
        statement = (
            select(MissionRecord)
            .options(selectinload(MissionRecord.steps))
            .where(MissionRecord.id == mission_id)
        )
        record = self.session.scalar(statement)
        return _to_data(record) if record else None

    def get_active_for_vehicle(self, vehicle_id: str) -> Optional[MissionData]:
        statement = (
            select(MissionRecord)
            .options(selectinload(MissionRecord.steps))
            .where(MissionRecord.vehicle_id == vehicle_id, MissionRecord.active.is_(True))
        )
        record = self.session.scalar(statement)
        return _to_data(record) if record else None

    def list_active(self) -> list[MissionData]:
        statement = (
            select(MissionRecord)
            .options(selectinload(MissionRecord.steps))
            .where(MissionRecord.active.is_(True))
            .order_by(MissionRecord.assigned_at, MissionRecord.id)
        )
        return [_to_data(record) for record in self.session.scalars(statement)]


def _to_data(record: MissionRecord) -> MissionData:
    return MissionData(
        id=record.id,
        order_id=record.order_id,
        vehicle_id=record.vehicle_id,
        status=MissionStatus(record.status),
        active=record.active,
        assigned_at=record.assigned_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        steps=tuple(
            MissionStepData(
                id=step.id,
                sequence_no=step.sequence_no,
                step_type=MissionStepType(step.step_type),
                status=MissionStepStatus(step.status),
                start_node_id=step.start_node_id,
                end_node_id=step.end_node_id,
                details=dict(step.details_json),
            )
            for step in sorted(record.steps, key=lambda item: item.sequence_no)
        ),
    )
