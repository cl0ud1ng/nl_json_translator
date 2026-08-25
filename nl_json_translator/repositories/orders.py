from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import OrderPriority, OrderStatus
from nl_json_translator.infrastructure.orm_models import TransportOrderRecord


_PRIORITY_RANK = {
    OrderPriority.URGENT: 0,
    OrderPriority.HIGH: 1,
    OrderPriority.NORMAL: 2,
    OrderPriority.LOW: 3,
}


@dataclass(frozen=True)
class OrderData:
    id: str
    pickup_location_id: Optional[str]
    dropoff_location_id: Optional[str]
    cargo: dict[str, Any]
    priority: OrderPriority
    status: OrderStatus
    requested_vehicle_id: Optional[str]
    earliest_start_at: Optional[datetime]
    deadline_at: Optional[datetime]
    created_at: datetime


class OrderRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, order_id: str) -> Optional[OrderData]:
        record = self.session.get(TransportOrderRecord, order_id)
        return _to_data(record) if record else None

    def list_ready(self, *, now: Optional[datetime] = None) -> list[OrderData]:
        current_time = now or datetime.now(timezone.utc)
        records = list(
            self.session.scalars(
                select(TransportOrderRecord).where(
                    TransportOrderRecord.status == OrderStatus.RESOLVED.value
                )
            )
        )
        ready = [
            _to_data(record)
            for record in records
            if record.earliest_start_at is None
            or _as_utc(record.earliest_start_at) <= _as_utc(current_time)
        ]
        maximum_time = datetime.max.replace(tzinfo=timezone.utc)
        return sorted(
            ready,
            key=lambda order: (
                _PRIORITY_RANK[order.priority],
                _as_utc(order.deadline_at) if order.deadline_at else maximum_time,
                _as_utc(order.created_at),
                order.id,
            ),
        )

    def claim_for_assignment(self, order_id: str) -> bool:
        result = self.session.execute(
            update(TransportOrderRecord)
            .where(
                TransportOrderRecord.id == order_id,
                TransportOrderRecord.status == OrderStatus.RESOLVED.value,
            )
            .values(status=OrderStatus.ASSIGNED.value)
        )
        return result.rowcount == 1

    def count_by_status(self) -> dict[OrderStatus, int]:
        statement = select(TransportOrderRecord.status, func.count()).group_by(
            TransportOrderRecord.status
        )
        return {
            OrderStatus(status): count
            for status, count in self.session.execute(statement)
        }

    def mark_delivered(self, order_id: str) -> bool:
        result = self.session.execute(
            update(TransportOrderRecord)
            .where(
                TransportOrderRecord.id == order_id,
                TransportOrderRecord.status == OrderStatus.ASSIGNED.value,
            )
            .values(status=OrderStatus.DELIVERED.value)
        )
        return result.rowcount == 1


def _to_data(record: TransportOrderRecord) -> OrderData:
    return OrderData(
        id=record.id,
        pickup_location_id=record.pickup_location_id,
        dropoff_location_id=record.dropoff_location_id,
        cargo=dict(record.cargo_json),
        priority=OrderPriority(record.priority),
        status=OrderStatus(record.status),
        requested_vehicle_id=record.requested_vehicle_id,
        earliest_start_at=record.earliest_start_at,
        deadline_at=record.deadline_at,
        created_at=record.created_at,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
