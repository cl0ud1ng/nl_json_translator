from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import VehicleStatus
from nl_json_translator.infrastructure.orm_models import VehicleRecord


@dataclass(frozen=True)
class VehicleData:
    id: str
    name: str
    current_node_id: str
    heading: float
    status: VehicleStatus
    capacity_weight: float
    capacity_volume: float
    battery_level: float
    capabilities: tuple[str, ...]
    telemetry_updated_at: datetime


class VehicleRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, vehicle_id: str) -> Optional[VehicleData]:
        record = self.session.get(VehicleRecord, vehicle_id)
        return _to_data(record) if record else None

    def list_all(self) -> list[VehicleData]:
        records = self.session.scalars(select(VehicleRecord).order_by(VehicleRecord.id))
        return [_to_data(record) for record in records]

    def reserve(self, vehicle_id: str) -> bool:
        result = self.session.execute(
            update(VehicleRecord)
            .where(
                VehicleRecord.id == vehicle_id,
                VehicleRecord.status == VehicleStatus.IDLE.value,
            )
            .values(status=VehicleStatus.RESERVED.value)
        )
        return result.rowcount == 1

    def finish_mission(
        self,
        vehicle_id: str,
        *,
        node_id: str,
        heading: float,
        telemetry_updated_at: datetime,
    ) -> bool:
        result = self.session.execute(
            update(VehicleRecord)
            .where(VehicleRecord.id == vehicle_id)
            .values(
                current_node_id=node_id,
                heading=heading,
                status=VehicleStatus.IDLE.value,
                telemetry_updated_at=telemetry_updated_at,
            )
        )
        return result.rowcount == 1


def _to_data(record: VehicleRecord) -> VehicleData:
    return VehicleData(
        id=record.id,
        name=record.name,
        current_node_id=record.current_node_id,
        heading=record.heading,
        status=VehicleStatus(record.status),
        capacity_weight=record.capacity_weight,
        capacity_volume=record.capacity_volume,
        battery_level=record.battery_level,
        capabilities=tuple(record.capabilities),
        telemetry_updated_at=record.telemetry_updated_at,
    )
