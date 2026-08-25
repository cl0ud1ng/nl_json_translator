from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import AgentEventType, MissionStepType, VehicleStatus
from nl_json_translator.repositories.events import EventRepository
from nl_json_translator.repositories.maps import MapData
from nl_json_translator.repositories.missions import MissionData, MissionRepository
from nl_json_translator.repositories.orders import OrderRepository
from nl_json_translator.repositories.vehicles import VehicleRepository

from .fleet_view_service import FleetSnapshot, FleetVehicleView
from .cooperative_routing_service import (
    CooperativeRoutingService,
    ReservationTable,
    TimedRoute,
)


@dataclass(frozen=True)
class VehicleRuntimeState:
    vehicle_id: str
    node_id: str
    heading: float
    status: VehicleStatus
    phase: str
    mission_id: Optional[str]
    order_id: Optional[str]
    cargo_name: Optional[str]
    carrying_cargo: bool
    executed_node_ids: tuple[str, ...]
    remaining_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class FleetRuntimeFrame:
    index: int
    vehicles: tuple[VehicleRuntimeState, ...]


@dataclass(frozen=True)
class FleetSimulation:
    snapshot: FleetSnapshot
    frames: tuple[FleetRuntimeFrame, ...]
    mission_ids: tuple[str, ...]


class FleetSimulationService:
    def __init__(self, session: Session):
        self.missions = MissionRepository(session)
        self.orders = OrderRepository(session)
        self.vehicles = VehicleRepository(session)
        self.events = EventRepository(session)

    def build(
        self,
        map_data: MapData,
        snapshot: FleetSnapshot,
        *,
        mission_ids: Optional[set[str]] = None,
        load_ticks: int = 3,
        unload_ticks: int = 3,
    ) -> FleetSimulation:
        selected_ids = mission_ids or {mission.id for mission in snapshot.active_missions}
        mission_by_id = {mission.id: mission for mission in snapshot.active_missions}
        reservations = ReservationTable(map_data, service_node_capacity=2)
        cooperative_routing = CooperativeRoutingService()
        timelines: dict[str, list[VehicleRuntimeState]] = {}
        selected_mission_ids: list[str] = []
        for vehicle in snapshot.vehicles:
            mission = (
                mission_by_id.get(vehicle.mission_id)
                if vehicle.mission_id in selected_ids
                else None
            )
            if mission:
                timeline, reposition_route, transport_route = _cooperative_mission_timeline(
                    map_data,
                    vehicle,
                    mission,
                    reservations,
                    cooperative_routing,
                    load_ticks=max(1, load_ticks),
                    unload_ticks=max(1, unload_ticks),
                )
                timelines[vehicle.id] = timeline
                self.missions.set_step_route(
                    mission.id,
                    MissionStepType.REPOSITION,
                    node_ids=reposition_route.node_ids,
                    wait_count=reposition_route.wait_count,
                )
                self.missions.set_step_route(
                    mission.id,
                    MissionStepType.TRANSPORT,
                    node_ids=transport_route.node_ids,
                    wait_count=transport_route.wait_count,
                )
                wait_count = reposition_route.wait_count + transport_route.wait_count
                self.events.append(
                    event_type=AgentEventType.ROUTE_PLANNED,
                    aggregate_type="mission",
                    aggregate_id=mission.id,
                    mission_id=mission.id,
                    order_id=mission.order_id,
                    vehicle_id=mission.vehicle_id,
                    payload={"wait_count": wait_count, "conflict_aware": True},
                )
                if wait_count:
                    self.events.append(
                        event_type=AgentEventType.WAIT_INSERTED,
                        aggregate_type="mission",
                        aggregate_id=mission.id,
                        mission_id=mission.id,
                        order_id=mission.order_id,
                        vehicle_id=mission.vehicle_id,
                        payload={"wait_count": wait_count},
                    )
                selected_mission_ids.append(mission.id)
            else:
                timelines[vehicle.id] = [_idle_state(vehicle)]

        frame_count = max((len(timeline) for timeline in timelines.values()), default=1)
        frames = tuple(
            FleetRuntimeFrame(
                index=index,
                vehicles=tuple(
                    timelines[vehicle.id][min(index, len(timelines[vehicle.id]) - 1)]
                    for vehicle in snapshot.vehicles
                ),
            )
            for index in range(frame_count)
        )
        return FleetSimulation(snapshot, frames, tuple(selected_mission_ids))

    def complete(
        self,
        simulation: FleetSimulation,
        *,
        completed_at: Optional[datetime] = None,
    ) -> int:
        if not simulation.frames:
            return 0
        timestamp = completed_at or datetime.now(timezone.utc)
        final_states = {
            state.mission_id: state
            for state in simulation.frames[-1].vehicles
            if state.mission_id
        }
        completed = 0
        for mission_id in simulation.mission_ids:
            final_state = final_states.get(mission_id)
            if not final_state:
                continue
            mission = self.missions.complete(mission_id, completed_at=timestamp)
            if not mission:
                continue
            self.orders.mark_delivered(mission.order_id)
            self.vehicles.finish_mission(
                mission.vehicle_id,
                node_id=final_state.node_id,
                heading=final_state.heading,
                telemetry_updated_at=timestamp,
            )
            self.events.append(
                event_type=AgentEventType.MISSION_COMPLETED,
                aggregate_type="mission",
                aggregate_id=mission.id,
                mission_id=mission.id,
                order_id=mission.order_id,
                vehicle_id=mission.vehicle_id,
                payload={
                    "final_node_id": final_state.node_id,
                    "cargo_name": final_state.cargo_name,
                },
            )
            completed += 1
        return completed


def _cooperative_mission_timeline(
    map_data: MapData,
    vehicle: FleetVehicleView,
    mission: MissionData,
    reservations: ReservationTable,
    routing: CooperativeRoutingService,
    *,
    load_ticks: int,
    unload_ticks: int,
) -> tuple[list[VehicleRuntimeState], TimedRoute, TimedRoute]:
    pickup_node = _step_endpoint(mission, MissionStepType.REPOSITION, "end_node_id")
    dropoff_node = _step_endpoint(mission, MissionStepType.TRANSPORT, "end_node_id")
    reposition_route = routing.plan(
        map_data,
        reservations,
        start_node_id=vehicle.node_id,
        goal_node_id=pickup_node,
        start_time=0,
        goal_hold_steps=load_ticks,
    )
    transport_start = reposition_route.end_time + load_ticks
    transport_route = routing.plan(
        map_data,
        reservations,
        start_node_id=pickup_node,
        goal_node_id=dropoff_node,
        start_time=transport_start,
        goal_hold_steps=unload_ticks + 160,
    )
    reposition = reposition_route.node_ids
    transport = transport_route.node_ids
    full_route = _join_routes(reposition, transport)
    pickup_index = max(0, len(reposition) - 1)
    timeline: list[VehicleRuntimeState] = []
    heading = vehicle.heading

    for index, node_id in enumerate(reposition):
        waiting = index > 0 and reposition[index - 1] == node_id
        if index and not waiting:
            heading = _heading(map_data, reposition[index - 1], node_id, heading)
        timeline.append(
            _runtime_state(
                vehicle,
                node_id=node_id,
                heading=heading,
                status=VehicleStatus.BLOCKED if waiting else VehicleStatus.TO_PICKUP,
                phase=(
                    "等待避让"
                    if waiting
                    else "前往取货点" if index < len(reposition) - 1 else "到达取货点"
                ),
                carrying=False,
                executed=full_route[: index + 1],
                remaining=full_route[index + 1 :],
            )
        )

    pickup_node = reposition[-1]
    for tick in range(1, load_ticks + 1):
        loaded = tick == load_ticks
        timeline.append(
            _runtime_state(
                vehicle,
                node_id=pickup_node,
                heading=heading,
                status=VehicleStatus.LOADING,
                phase="装货完成" if loaded else f"装货中 {tick}/{load_ticks}",
                carrying=loaded,
                executed=full_route[: pickup_index + 1],
                remaining=full_route[pickup_index:],
            )
        )

    for route_index, node_id in enumerate(transport[1:], start=1):
        previous = transport[route_index - 1]
        waiting = previous == node_id
        if not waiting:
            heading = _heading(map_data, previous, node_id, heading)
        full_index = pickup_index + route_index
        timeline.append(
            _runtime_state(
                vehicle,
                node_id=node_id,
                heading=heading,
                status=VehicleStatus.BLOCKED if waiting else VehicleStatus.TO_DROPOFF,
                phase=(
                    "等待避让"
                    if waiting
                    else "到达目标点"
                    if route_index == len(transport) - 1
                    else "载货运输中"
                ),
                carrying=True,
                executed=full_route[: full_index + 1],
                remaining=full_route[full_index + 1 :],
            )
        )

    dropoff_node = transport[-1]
    for tick in range(1, unload_ticks + 1):
        unloaded = tick == unload_ticks
        timeline.append(
            _runtime_state(
                vehicle,
                node_id=dropoff_node,
                heading=heading,
                status=VehicleStatus.UNLOADING,
                phase="卸货完成" if unloaded else f"卸货中 {tick}/{unload_ticks}",
                carrying=not unloaded,
                executed=full_route,
                remaining=(),
            )
        )
    timeline.append(
        _runtime_state(
            vehicle,
            node_id=dropoff_node,
            heading=heading,
            status=VehicleStatus.IDLE,
            phase="任务完成",
            carrying=False,
            executed=full_route,
            remaining=(),
        )
    )
    reservation_timeline = (
        reposition
        + (pickup_node,) * load_ticks
        + transport[1:]
        + (dropoff_node,) * (unload_ticks + 161)
    )
    reservations.reserve_timeline(reservation_timeline)
    return timeline, reposition_route, transport_route


def _runtime_state(
    vehicle: FleetVehicleView,
    *,
    node_id: str,
    heading: float,
    status: VehicleStatus,
    phase: str,
    carrying: bool,
    executed: tuple[str, ...],
    remaining: tuple[str, ...],
) -> VehicleRuntimeState:
    return VehicleRuntimeState(
        vehicle_id=vehicle.id,
        node_id=node_id,
        heading=heading,
        status=status,
        phase=phase,
        mission_id=vehicle.mission_id,
        order_id=vehicle.order_id,
        cargo_name=vehicle.cargo_name,
        carrying_cargo=carrying,
        executed_node_ids=executed,
        remaining_node_ids=remaining,
    )


def _idle_state(vehicle: FleetVehicleView) -> VehicleRuntimeState:
    return VehicleRuntimeState(
        vehicle_id=vehicle.id,
        node_id=vehicle.node_id,
        heading=vehicle.heading,
        status=vehicle.status,
        phase="等待任务",
        mission_id=None,
        order_id=None,
        cargo_name=None,
        carrying_cargo=False,
        executed_node_ids=(vehicle.node_id,),
        remaining_node_ids=(),
    )


def _step_endpoint(
    mission: MissionData,
    step_type: MissionStepType,
    attribute: str,
) -> str:
    for step in mission.steps:
        if step.step_type is step_type:
            value = getattr(step, attribute)
            if value:
                return value
    raise ValueError(f"mission {mission.id} has no {step_type.value} endpoint")


def find_runtime_conflicts(
    map_data: MapData,
    simulation: FleetSimulation,
) -> list[str]:
    service_nodes = {location.node_id for location in map_data.locations.values()}
    conflicts: list[str] = []
    for frame_index, frame in enumerate(simulation.frames):
        active = [state for state in frame.vehicles if state.mission_id]
        node_counts: dict[str, int] = {}
        for state in active:
            node_counts[state.node_id] = node_counts.get(state.node_id, 0) + 1
        for node_id, occupancy in node_counts.items():
            capacity = 2 if node_id in service_nodes else 1
            if occupancy > capacity:
                conflicts.append(
                    f"node conflict at t={frame_index}: {node_id} occupancy={occupancy}"
                )
        if frame_index == 0:
            continue
        previous = {
            state.vehicle_id: state
            for state in simulation.frames[frame_index - 1].vehicles
            if state.mission_id
        }
        for first_index, first in enumerate(active):
            for second in active[first_index + 1 :]:
                first_previous = previous.get(first.vehicle_id)
                second_previous = previous.get(second.vehicle_id)
                if not first_previous or not second_previous:
                    continue
                if (
                    first_previous.node_id == second.node_id
                    and second_previous.node_id == first.node_id
                    and first.node_id != second.node_id
                ):
                    conflicts.append(
                        f"head-on edge conflict at t={frame_index}: "
                        f"{first.vehicle_id}/{second.vehicle_id}"
                    )
    return conflicts


def _join_routes(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...]:
    if not first:
        return second
    if not second:
        return first
    return first + second[1:] if first[-1] == second[0] else first + second


def _heading(map_data: MapData, start_id: str, end_id: str, fallback: float) -> float:
    start = map_data.nodes.get(start_id)
    end = map_data.nodes.get(end_id)
    if not start or not end:
        return fallback
    dx, dy = end.x - start.x, end.y - start.y
    if dx > 0:
        return 0.0
    if dy > 0:
        return 90.0
    if dx < 0:
        return 180.0
    if dy < 0:
        return 270.0
    return fallback
