from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import AgentEventType, MissionStepType, VehicleStatus
from nl_json_translator.repositories.events import EventRepository
from nl_json_translator.repositories.maps import MapData, MapRepository
from nl_json_translator.repositories.missions import (
    MissionData,
    MissionRepository,
    MissionStepDefinition,
)
from nl_json_translator.repositories.orders import OrderData, OrderRepository
from nl_json_translator.repositories.vehicles import VehicleData, VehicleRepository

from .routing_service import RoutePlan, RoutingService


class DispatchConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class DispatchPolicy:
    telemetry_max_age: timedelta = timedelta(minutes=5)
    battery_reserve: float = 10.0
    battery_per_distance: float = 0.5
    battery_penalty_weight: float = 0.02


@dataclass(frozen=True)
class CandidateEvaluation:
    vehicle_id: str
    vehicle_name: str
    eligible: bool
    cost: Optional[float]
    reasons: tuple[str, ...]
    reposition_route: Optional[RoutePlan] = None


@dataclass(frozen=True)
class DispatchResult:
    order_id: str
    mission: Optional[MissionData]
    selected_vehicle_id: Optional[str]
    selected_cost: Optional[float]
    transport_route: Optional[RoutePlan]
    candidates: tuple[CandidateEvaluation, ...]

    @property
    def assigned(self) -> bool:
        return self.mission is not None


class DispatchService:
    def __init__(self, session: Session, *, policy: Optional[DispatchPolicy] = None):
        self.session = session
        self.policy = policy or DispatchPolicy()
        self.orders = OrderRepository(session)
        self.vehicles = VehicleRepository(session)
        self.missions = MissionRepository(session)
        self.events = EventRepository(session)
        self.map_data = MapRepository(session).load()
        self.routing = RoutingService()

    def dispatch_next(self, *, now: Optional[datetime] = None) -> Optional[DispatchResult]:
        ready = self.orders.list_ready(now=now)
        if not ready:
            return None
        return self.dispatch_order(ready[0].id, now=now)

    def dispatch_all_ready(
        self,
        *,
        now: Optional[datetime] = None,
        max_assignments: Optional[int] = None,
    ) -> tuple[DispatchResult, ...]:
        """Try each ready order once, preserving priority order and current fleet state."""

        results: list[DispatchResult] = []
        assignment_count = 0
        for order in self.orders.list_ready(now=now):
            if max_assignments is not None and assignment_count >= max_assignments:
                break
            result = self.dispatch_order(order.id, now=now)
            results.append(result)
            if result.assigned:
                assignment_count += 1
        return tuple(results)

    def dispatch_order(
        self, order_id: str, *, now: Optional[datetime] = None
    ) -> DispatchResult:
        order = self.orders.get(order_id)
        if not order:
            raise ValueError(f'Unknown order "{order_id}"')
        if order.status.value != "RESOLVED":
            raise ValueError(f'Order "{order_id}" is not RESOLVED')
        pickup_node_id, dropoff_node_id = self._location_nodes(order)
        transport_route = self.routing.shortest_route(
            self.map_data, pickup_node_id, dropoff_node_id
        )
        if not transport_route:
            raise ValueError(f'No route for order "{order_id}" pickup to dropoff')

        current_time = now or datetime.now(timezone.utc)
        candidates = tuple(
            self._evaluate_vehicle(
                order,
                vehicle,
                pickup_node_id,
                transport_route,
                current_time,
            )
            for vehicle in self.vehicles.list_all()
        )
        eligible = [candidate for candidate in candidates if candidate.eligible]
        if not eligible:
            return DispatchResult(order.id, None, None, None, transport_route, candidates)
        selected = min(eligible, key=lambda candidate: (candidate.cost, candidate.vehicle_id))
        vehicle = self.vehicles.get(selected.vehicle_id)
        if not vehicle or not selected.reposition_route:
            raise DispatchConflictError("selected vehicle disappeared before assignment")

        with self.session.begin_nested():
            if not self.orders.claim_for_assignment(order.id):
                raise DispatchConflictError(f'Order "{order.id}" was already assigned')
            if not self.vehicles.reserve(vehicle.id):
                raise DispatchConflictError(f'Vehicle "{vehicle.id}" is no longer idle')
            mission = self.missions.create(
                order_id=order.id,
                vehicle_id=vehicle.id,
                steps=self._build_steps(
                    vehicle,
                    pickup_node_id,
                    dropoff_node_id,
                    selected.reposition_route,
                    transport_route,
                ),
            )
            common = {
                "order_id": order.id,
                "mission_id": mission.id,
                "vehicle_id": vehicle.id,
            }
            self.events.append(
                event_type=AgentEventType.ORDER_ASSIGNED,
                aggregate_type="order",
                aggregate_id=order.id,
                payload={"cost": selected.cost},
                **common,
            )
            self.events.append(
                event_type=AgentEventType.VEHICLE_RESERVED,
                aggregate_type="vehicle",
                aggregate_id=vehicle.id,
                **common,
            )
            self.events.append(
                event_type=AgentEventType.MISSION_CREATED,
                aggregate_type="mission",
                aggregate_id=mission.id,
                payload={"step_count": len(mission.steps)},
                **common,
            )

        return DispatchResult(
            order.id,
            mission,
            vehicle.id,
            selected.cost,
            transport_route,
            candidates,
        )

    def _location_nodes(self, order: OrderData) -> tuple[str, str]:
        if not order.pickup_location_id or not order.dropoff_location_id:
            raise ValueError(f'Order "{order.id}" has unresolved locations')
        pickup = self.map_data.locations.get(order.pickup_location_id)
        dropoff = self.map_data.locations.get(order.dropoff_location_id)
        if not pickup or not dropoff:
            raise ValueError(f'Order "{order.id}" references a disabled or unknown location')
        return pickup.node_id, dropoff.node_id

    def _evaluate_vehicle(
        self,
        order: OrderData,
        vehicle: VehicleData,
        pickup_node_id: str,
        transport_route: RoutePlan,
        now: datetime,
    ) -> CandidateEvaluation:
        reasons: list[str] = []
        if order.requested_vehicle_id and vehicle.id != order.requested_vehicle_id:
            reasons.append("not_requested_vehicle")
        if vehicle.status is not VehicleStatus.IDLE:
            reasons.append("vehicle_not_idle")
        telemetry_age = _as_utc(now) - _as_utc(vehicle.telemetry_updated_at)
        if telemetry_age > self.policy.telemetry_max_age:
            reasons.append("telemetry_stale")

        weight = float(order.cargo.get("weight_kg") or 0.0)
        volume = float(order.cargo.get("volume_m3") or 0.0)
        if weight > vehicle.capacity_weight:
            reasons.append("weight_capacity_exceeded")
        if volume > vehicle.capacity_volume:
            reasons.append("volume_capacity_exceeded")
        required = {str(item).casefold() for item in order.cargo.get("required_capabilities", [])}
        available = {item.casefold() for item in vehicle.capabilities}
        if not required.issubset(available):
            reasons.append("missing_capabilities")

        reposition_route = self.routing.shortest_route(
            self.map_data, vehicle.current_node_id, pickup_node_id
        )
        if not reposition_route:
            reasons.append("pickup_unreachable")
        total_distance = (
            reposition_route.distance + transport_route.distance if reposition_route else 0.0
        )
        required_battery = (
            self.policy.battery_reserve + total_distance * self.policy.battery_per_distance
        )
        if reposition_route and vehicle.battery_level < required_battery:
            reasons.append("battery_insufficient")

        cost = None
        if not reasons and reposition_route:
            battery_penalty = (100.0 - vehicle.battery_level) * self.policy.battery_penalty_weight
            cost = round(total_distance + battery_penalty, 4)
        return CandidateEvaluation(
            vehicle_id=vehicle.id,
            vehicle_name=vehicle.name,
            eligible=not reasons,
            cost=cost,
            reasons=tuple(reasons),
            reposition_route=reposition_route,
        )

    @staticmethod
    def _build_steps(
        vehicle: VehicleData,
        pickup_node_id: str,
        dropoff_node_id: str,
        reposition: RoutePlan,
        transport: RoutePlan,
    ) -> list[MissionStepDefinition]:
        return [
            MissionStepDefinition(
                MissionStepType.REPOSITION,
                start_node_id=vehicle.current_node_id,
                end_node_id=pickup_node_id,
                details=_route_details(reposition),
            ),
            MissionStepDefinition(
                MissionStepType.LOAD,
                start_node_id=pickup_node_id,
                end_node_id=pickup_node_id,
            ),
            MissionStepDefinition(
                MissionStepType.TRANSPORT,
                start_node_id=pickup_node_id,
                end_node_id=dropoff_node_id,
                details=_route_details(transport),
            ),
            MissionStepDefinition(
                MissionStepType.UNLOAD,
                start_node_id=dropoff_node_id,
                end_node_id=dropoff_node_id,
            ),
            MissionStepDefinition(
                MissionStepType.COMPLETE,
                start_node_id=dropoff_node_id,
                end_node_id=dropoff_node_id,
            ),
        ]


def _route_details(route: RoutePlan) -> dict[str, object]:
    return {
        "planned_node_ids": list(route.node_ids),
        "distance": route.distance,
        "travel_time": route.travel_time,
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
