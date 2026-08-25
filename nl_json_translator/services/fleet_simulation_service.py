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
        timelines: dict[str, list[VehicleRuntimeState]] = {}
        selected_mission_ids: list[str] = []
        for vehicle in snapshot.vehicles:
            mission = (
                mission_by_id.get(vehicle.mission_id)
                if vehicle.mission_id in selected_ids
                else None
            )
            if mission:
                timelines[vehicle.id] = _mission_timeline(
                    map_data,
                    vehicle,
                    mission,
                    load_ticks=max(1, load_ticks),
                    unload_ticks=max(1, unload_ticks),
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


def _mission_timeline(
    map_data: MapData,
    vehicle: FleetVehicleView,
    mission: MissionData,
    *,
    load_ticks: int,
    unload_ticks: int,
) -> list[VehicleRuntimeState]:
    reposition = _step_route(mission, MissionStepType.REPOSITION) or (vehicle.node_id,)
    transport = _step_route(mission, MissionStepType.TRANSPORT)
    if not transport:
        transport = (reposition[-1],)
    full_route = _join_routes(reposition, transport)
    pickup_index = max(0, len(reposition) - 1)
    timeline: list[VehicleRuntimeState] = []
    heading = vehicle.heading

    for index, node_id in enumerate(reposition):
        if index:
            heading = _heading(map_data, reposition[index - 1], node_id, heading)
        timeline.append(
            _runtime_state(
                vehicle,
                node_id=node_id,
                heading=heading,
                status=VehicleStatus.TO_PICKUP,
                phase="前往取货点" if index < len(reposition) - 1 else "到达取货点",
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
        heading = _heading(map_data, previous, node_id, heading)
        full_index = pickup_index + route_index
        timeline.append(
            _runtime_state(
                vehicle,
                node_id=node_id,
                heading=heading,
                status=VehicleStatus.TO_DROPOFF,
                phase=(
                    "到达目标点"
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
    return timeline


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


def _step_route(mission: MissionData, step_type: MissionStepType) -> tuple[str, ...]:
    for step in mission.steps:
        if step.step_type is not step_type:
            continue
        route = step.details.get("planned_node_ids")
        if isinstance(route, list):
            return tuple(node_id for node_id in route if isinstance(node_id, str))
    return ()


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
