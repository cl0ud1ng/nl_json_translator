from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import MissionStatus, OrderStatus, VehicleStatus
from nl_json_translator.repositories.events import AgentEventData, EventRepository
from nl_json_translator.repositories.missions import MissionData, MissionRepository
from nl_json_translator.repositories.orders import OrderRepository
from nl_json_translator.repositories.vehicles import VehicleRepository


FLEET_COLORS = (
    "#0f766e",
    "#2563eb",
    "#c2410c",
    "#7c3aed",
    "#be123c",
    "#4d7c0f",
    "#0369a1",
    "#a16207",
)


@dataclass(frozen=True)
class FleetVehicleView:
    id: str
    name: str
    node_id: str
    heading: float
    status: VehicleStatus
    battery_level: float
    color: str
    mission_id: Optional[str]
    mission_status: Optional[MissionStatus]
    order_id: Optional[str]
    planned_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class FleetSnapshot:
    vehicles: tuple[FleetVehicleView, ...]
    active_missions: tuple[MissionData, ...]
    order_counts: dict[OrderStatus, int]
    recent_events: tuple[AgentEventData, ...]

    @property
    def idle_vehicle_count(self) -> int:
        return sum(vehicle.status is VehicleStatus.IDLE for vehicle in self.vehicles)


class FleetViewService:
    def __init__(self, session: Session):
        self.vehicles = VehicleRepository(session)
        self.missions = MissionRepository(session)
        self.orders = OrderRepository(session)
        self.events = EventRepository(session)

    def snapshot(self, *, event_limit: int = 30) -> FleetSnapshot:
        missions = tuple(self.missions.list_active())
        mission_by_vehicle = {mission.vehicle_id: mission for mission in missions}
        vehicles = []
        for index, vehicle in enumerate(self.vehicles.list_all()):
            mission = mission_by_vehicle.get(vehicle.id)
            vehicles.append(
                FleetVehicleView(
                    id=vehicle.id,
                    name=vehicle.name,
                    node_id=vehicle.current_node_id,
                    heading=vehicle.heading,
                    status=vehicle.status,
                    battery_level=vehicle.battery_level,
                    color=FLEET_COLORS[index % len(FLEET_COLORS)],
                    mission_id=mission.id if mission else None,
                    mission_status=mission.status if mission else None,
                    order_id=mission.order_id if mission else None,
                    planned_node_ids=_planned_nodes(mission) if mission else (),
                )
            )
        return FleetSnapshot(
            vehicles=tuple(vehicles),
            active_missions=missions,
            order_counts=self.orders.count_by_status(),
            recent_events=tuple(self.events.list_recent(limit=event_limit)),
        )


def _planned_nodes(mission: MissionData) -> tuple[str, ...]:
    node_ids: list[str] = []
    for step in mission.steps:
        planned = step.details.get("planned_node_ids")
        if not isinstance(planned, list):
            continue
        for node_id in planned:
            if not isinstance(node_id, str):
                continue
            if not node_ids or node_ids[-1] != node_id:
                node_ids.append(node_id)
    return tuple(node_ids)
