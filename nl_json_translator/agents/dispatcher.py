from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import (
    AgentCommandType,
    AgentEventType,
    AgentStatus,
    BatchStatus,
)
from nl_json_translator.domain.schemas import TransportRequestDraft
from nl_json_translator.infrastructure.orm_models import VehicleAgentStateRecord
from nl_json_translator.repositories.batches import BatchRepository
from nl_json_translator.repositories.commands import CommandRepository
from nl_json_translator.repositories.events import EventRepository
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.repositories.reservations import ReservationRepository
from nl_json_translator.services.dispatch_service import DispatchResult, DispatchService
from nl_json_translator.services.fleet_simulation_service import (
    FleetSimulation,
    FleetSimulationService,
    VehicleRuntimeState,
)
from nl_json_translator.services.fleet_view_service import FleetViewService
from nl_json_translator.services.order_service import OrderCreationResult, OrderService


@dataclass(frozen=True)
class BatchDispatch:
    batch_id: str
    orders: tuple[OrderCreationResult, ...]
    dispatches: tuple[DispatchResult, ...]
    planned_simulation: Optional[FleetSimulation]


class DispatcherAgent:
    """The single owner of order allocation and global route reservations."""

    agent_id = "dispatcher/main"

    def __init__(self, session: Session):
        self.session = session
        self.batches = BatchRepository(session)
        self.commands = CommandRepository(session)
        self.events = EventRepository(session)
        self.reservations = ReservationRepository(session)

    def submit(
        self,
        request: TransportRequestDraft,
        *,
        natural_language: Optional[str] = None,
        provider_response_id: Optional[str] = None,
        provider_model: Optional[str] = None,
        provider_usage: Optional[dict[str, object]] = None,
        batch_id: Optional[str] = None,
    ) -> BatchDispatch:
        resolved_batch_id = batch_id or f"batch_{uuid4().hex}"
        constraints = request.dispatch_constraints.model_dump(mode="json")
        self.batches.create(
            batch_id=resolved_batch_id,
            natural_language=natural_language,
            constraints=constraints,
            provider_response_id=provider_response_id,
            provider_model=provider_model,
            provider_usage=provider_usage,
        )
        order_service = OrderService(self.session)
        orders = tuple(
            order_service.create_from_intent(
                draft,
                batch_id=resolved_batch_id,
                idempotency_key=f"{resolved_batch_id}-{index}",
            )
            for index, draft in enumerate(request.orders, start=1)
        )
        if any(not order.formal_order for order in orders):
            self.batches.set_status(resolved_batch_id, BatchStatus.NEEDS_REVIEW)
            return BatchDispatch(resolved_batch_id, orders, (), None)

        require_all = request.dispatch_constraints.distinct_vehicle_per_order
        dispatches = DispatchService(self.session).dispatch_batch(
            tuple(order.order_id for order in orders),
            require_all=require_all,
        )
        assigned = tuple(item for item in dispatches if item.assigned)
        if not assigned:
            self.batches.set_status(resolved_batch_id, BatchStatus.WAITING)
            return BatchDispatch(resolved_batch_id, orders, dispatches, None)

        mission_ids = {item.mission.id for item in assigned if item.mission}
        snapshot = FleetViewService(self.session).snapshot()
        planned = FleetSimulationService(self.session).build(
            MapRepository(self.session).load(),
            snapshot,
            mission_ids=mission_ids,
        )
        for dispatch in assigned:
            assert dispatch.mission and dispatch.selected_vehicle_id
            states = _mission_states(
                planned,
                vehicle_id=dispatch.selected_vehicle_id,
                mission_id=dispatch.mission.id,
            )
            agent_id = f"vehicle/{dispatch.selected_vehicle_id}"
            agent_state = self.session.get(
                VehicleAgentStateRecord, dispatch.selected_vehicle_id
            )
            if not agent_state:
                self.session.add(
                    VehicleAgentStateRecord(
                        vehicle_id=dispatch.selected_vehicle_id,
                        agent_id=agent_id,
                        status=AgentStatus.READY.value,
                    )
                )
            command = self.commands.enqueue(
                target_agent_id=agent_id,
                command_type=AgentCommandType.ASSIGN_MISSION,
                idempotency_key=f"assign-{dispatch.mission.id}-v1",
                correlation_id=resolved_batch_id,
                vehicle_id=dispatch.selected_vehicle_id,
                mission_id=dispatch.mission.id,
                payload={
                    "batch_id": resolved_batch_id,
                    "route_version": 1,
                    "states": [_serialize_state(state) for state in states],
                },
            )
            self.reservations.replace_timeline(
                mission_id=dispatch.mission.id,
                vehicle_id=dispatch.selected_vehicle_id,
                node_ids=tuple(state.node_id for state in states),
            )
            self.events.append(
                event_type=AgentEventType.COMMAND_ENQUEUED,
                aggregate_type="agent_command",
                aggregate_id=command.id,
                mission_id=dispatch.mission.id,
                order_id=dispatch.order_id,
                vehicle_id=dispatch.selected_vehicle_id,
                payload={"target_agent_id": agent_id},
            )
        self.batches.set_status(resolved_batch_id, BatchStatus.DISPATCHED)
        return BatchDispatch(resolved_batch_id, orders, dispatches, planned)


def _mission_states(
    simulation: FleetSimulation, *, vehicle_id: str, mission_id: str
) -> tuple[VehicleRuntimeState, ...]:
    states: list[VehicleRuntimeState] = []
    for frame in simulation.frames:
        state = next(item for item in frame.vehicles if item.vehicle_id == vehicle_id)
        if state.mission_id != mission_id:
            continue
        states.append(state)
        if state.phase == "任务完成":
            break
    if not states or states[-1].phase != "任务完成":
        raise RuntimeError(f"mission {mission_id} has no complete execution timeline")
    return tuple(states)


def _serialize_state(state: VehicleRuntimeState) -> dict[str, object]:
    return {
        "vehicle_id": state.vehicle_id,
        "node_id": state.node_id,
        "heading": state.heading,
        "status": state.status.value,
        "phase": state.phase,
        "mission_id": state.mission_id,
        "order_id": state.order_id,
        "cargo_name": state.cargo_name,
        "carrying_cargo": state.carrying_cargo,
        "executed_node_ids": list(state.executed_node_ids),
        "remaining_node_ids": list(state.remaining_node_ids),
    }
