from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import OrderStatus
from nl_json_translator.domain.schemas import TransportIntentDraft, TransportOrder
from nl_json_translator.infrastructure.orm_models import TransportOrderRecord, VehicleRecord
from nl_json_translator.repositories.locations import LocationRepository

from .location_resolver import (
    LocationResolution,
    LocationResolutionStatus,
    LocationResolver,
    UnknownLocationError,
)


@dataclass(frozen=True)
class OrderCreationResult:
    order_id: str
    status: OrderStatus
    formal_order: Optional[TransportOrder]
    pickup_resolution: Optional[LocationResolution]
    dropoff_resolution: Optional[LocationResolution]
    created: bool


class OrderService:
    def __init__(self, session: Session):
        self.session = session
        self.location_repository = LocationRepository(session)
        self.location_resolver = LocationResolver(self.location_repository)

    def create_from_intent(
        self,
        intent: TransportIntentDraft | dict[str, Any],
        *,
        idempotency_key: Optional[str] = None,
    ) -> OrderCreationResult:
        draft = (
            intent
            if isinstance(intent, TransportIntentDraft)
            else TransportIntentDraft.model_validate(intent)
        )
        if idempotency_key:
            existing = self.session.scalar(
                select(TransportOrderRecord).where(
                    TransportOrderRecord.idempotency_key == idempotency_key
                )
            )
            if existing:
                return self._existing_result(existing)

        pickup = self.location_resolver.resolve(draft.pickup_location_text)
        dropoff = self.location_resolver.resolve(draft.dropoff_location_text)
        unknown = [
            resolution.query
            for resolution in (pickup, dropoff)
            if resolution.status is LocationResolutionStatus.UNKNOWN
        ]
        if unknown:
            raise UnknownLocationError(f"Unknown location(s): {', '.join(unknown)}")

        requested_vehicle_id = self._resolve_vehicle(draft.vehicle_text)
        ambiguous = any(
            resolution.status is LocationResolutionStatus.AMBIGUOUS
            for resolution in (pickup, dropoff)
        )
        status = OrderStatus.NEEDS_REVIEW if ambiguous else OrderStatus.RESOLVED
        formal_order = None
        if not ambiguous:
            formal_order = TransportOrder(
                cargo=draft.cargo,
                pickup_location_id=pickup.require_location_id(),
                dropoff_location_id=dropoff.require_location_id(),
                requested_vehicle_id=requested_vehicle_id,
                priority=draft.priority,
                idempotency_key=idempotency_key,
            )

        record = TransportOrderRecord(
            id=f"order_{uuid4().hex}",
            pickup_location_id=pickup.location_id,
            dropoff_location_id=dropoff.location_id,
            pickup_location_text=draft.pickup_location_text,
            dropoff_location_text=draft.dropoff_location_text,
            cargo_json=draft.cargo.model_dump(mode="json"),
            priority=draft.priority.value,
            status=status.value,
            requested_vehicle_id=requested_vehicle_id,
            idempotency_key=idempotency_key,
        )
        self.session.add(record)
        self.session.flush()
        return OrderCreationResult(record.id, status, formal_order, pickup, dropoff, True)

    def _resolve_vehicle(self, vehicle_text: Optional[str]) -> Optional[str]:
        if not vehicle_text:
            return None
        normalized = vehicle_text.strip().casefold()
        matches = list(
            self.session.scalars(
                select(VehicleRecord).where(
                    or_(
                        VehicleRecord.id == vehicle_text,
                        VehicleRecord.name.ilike(vehicle_text),
                    )
                )
            )
        )
        exact = [
            vehicle
            for vehicle in matches
            if vehicle.id.casefold() == normalized or vehicle.name.casefold() == normalized
        ]
        if len(exact) != 1:
            raise ValueError(f'Unknown or ambiguous vehicle "{vehicle_text}"')
        return exact[0].id

    @staticmethod
    def _existing_result(record: TransportOrderRecord) -> OrderCreationResult:
        status = OrderStatus(record.status)
        formal_order = None
        if (
            status is OrderStatus.RESOLVED
            and record.pickup_location_id
            and record.dropoff_location_id
        ):
            formal_order = TransportOrder(
                cargo=record.cargo_json,
                pickup_location_id=record.pickup_location_id,
                dropoff_location_id=record.dropoff_location_id,
                requested_vehicle_id=record.requested_vehicle_id,
                priority=record.priority,
                idempotency_key=record.idempotency_key,
            )
        return OrderCreationResult(record.id, status, formal_order, None, None, False)
