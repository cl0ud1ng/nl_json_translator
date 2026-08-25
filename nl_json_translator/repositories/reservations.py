from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from nl_json_translator.infrastructure.orm_models import RouteReservationRecord


class ReservationRepository:
    def __init__(self, session: Session):
        self.session = session

    def replace_timeline(
        self,
        *,
        mission_id: str,
        vehicle_id: str,
        node_ids: tuple[str, ...],
        route_version: int = 1,
    ) -> int:
        self.session.execute(
            delete(RouteReservationRecord).where(
                RouteReservationRecord.mission_id == mission_id
            )
        )
        count = 0
        for time_slot, node_id in enumerate(node_ids):
            self.session.add(
                RouteReservationRecord(
                    id=f"reservation_{uuid4().hex}",
                    mission_id=mission_id,
                    vehicle_id=vehicle_id,
                    resource_type="node",
                    resource_id=node_id,
                    time_slot=time_slot,
                    route_version=route_version,
                )
            )
            count += 1
            if time_slot == 0 or node_ids[time_slot - 1] == node_id:
                continue
            start, end = sorted((node_ids[time_slot - 1], node_id))
            self.session.add(
                RouteReservationRecord(
                    id=f"reservation_{uuid4().hex}",
                    mission_id=mission_id,
                    vehicle_id=vehicle_id,
                    resource_type="edge",
                    resource_id=f"{start}|{end}",
                    time_slot=time_slot - 1,
                    route_version=route_version,
                )
            )
            count += 1
        self.session.flush()
        return count

    def consume_through(self, mission_id: str, time_slot: int) -> None:
        self.session.execute(
            update(RouteReservationRecord)
            .where(
                RouteReservationRecord.mission_id == mission_id,
                RouteReservationRecord.time_slot <= time_slot,
            )
            .values(active=False)
        )

    def release(self, mission_id: str) -> None:
        self.session.execute(
            update(RouteReservationRecord)
            .where(RouteReservationRecord.mission_id == mission_id)
            .values(active=False)
        )
