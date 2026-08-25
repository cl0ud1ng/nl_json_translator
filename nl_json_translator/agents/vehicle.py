from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import (
    AgentCommandStatus,
    AgentCommandType,
    AgentEventType,
    AgentStatus,
    BatchStatus,
    MissionStatus,
    OrderStatus,
    VehicleStatus,
)
from nl_json_translator.infrastructure.orm_models import (
    AgentCommandRecord,
    MissionRecord,
    TransportBatchRecord,
    TransportOrderRecord,
    VehicleAgentStateRecord,
    VehicleRecord,
)
from nl_json_translator.repositories.commands import CommandRepository
from nl_json_translator.repositories.events import EventRepository
from nl_json_translator.repositories.missions import MissionRepository
from nl_json_translator.repositories.orders import OrderRepository
from nl_json_translator.repositories.reservations import ReservationRepository
from nl_json_translator.repositories.vehicles import VehicleRepository
from nl_json_translator.services.fleet_simulation_service import VehicleRuntimeState


class VehicleAgent:
    """A durable subordinate agent that may mutate only its own vehicle mission."""

    def __init__(self, session: Session, vehicle_id: str):
        self.session = session
        self.vehicle_id = vehicle_id
        self.agent_id = f"vehicle/{vehicle_id}"
        self.commands = CommandRepository(session)
        self.events = EventRepository(session)
        self.reservations = ReservationRepository(session)
        self._ensure_state()

    def tick(self, time_slot: int) -> VehicleRuntimeState:
        timestamp = datetime.now(timezone.utc)
        agent_state = self.session.get(VehicleAgentStateRecord, self.vehicle_id)
        command = self.commands.next_for_agent(self.agent_id)
        if not command:
            agent_state.status = AgentStatus.READY.value
            agent_state.last_heartbeat_at = timestamp
            agent_state.state_version += 1
            return self._idle_state()
        if command.command_type is not AgentCommandType.ASSIGN_MISSION:
            raise RuntimeError(f"unsupported vehicle command {command.command_type.value}")
        if command.status is AgentCommandStatus.PENDING:
            self.commands.start(command.id)
            agent_state.status = AgentStatus.RUNNING.value
            agent_state.active_command_id = command.id
            agent_state.active_mission_id = command.mission_id
            agent_state.execution_cursor = 0
            agent_state.route_version = int(command.payload.get("route_version", 1))
            self.events.append(
                event_type=AgentEventType.COMMAND_ACCEPTED,
                aggregate_type="vehicle_agent",
                aggregate_id=self.agent_id,
                mission_id=command.mission_id,
                vehicle_id=self.vehicle_id,
                payload={"command_id": command.id},
            )
        raw_states = command.payload.get("states")
        if not isinstance(raw_states, list) or not raw_states:
            raise RuntimeError(f"command {command.id} has no execution states")
        cursor = agent_state.execution_cursor
        if cursor >= len(raw_states):
            cursor = len(raw_states) - 1
        state = _deserialize_state(raw_states[cursor])
        self._persist_tick(state, command.id, cursor, timestamp)
        agent_state.execution_cursor = cursor + 1
        agent_state.carrying_cargo = state.carrying_cargo
        agent_state.last_heartbeat_at = timestamp
        agent_state.state_version += 1
        self.reservations.consume_through(state.mission_id, cursor)
        if state.phase == "任务完成" or cursor + 1 >= len(raw_states):
            self._complete(state, command.id, timestamp)
        return state

    def _persist_tick(
        self,
        state: VehicleRuntimeState,
        command_id: str,
        cursor: int,
        timestamp: datetime,
    ) -> None:
        vehicle = self.session.get(VehicleRecord, self.vehicle_id)
        mission = self.session.get(MissionRecord, state.mission_id)
        order = self.session.get(TransportOrderRecord, state.order_id)
        if not vehicle or not mission or not order:
            raise RuntimeError(f"agent state references missing mission data for {command_id}")
        vehicle.current_node_id = state.node_id
        vehicle.heading = state.heading
        vehicle.status = state.status.value
        vehicle.telemetry_updated_at = timestamp
        if mission.status == MissionStatus.CREATED.value:
            mission.status = MissionStatus.RUNNING.value
            mission.started_at = timestamp
            self.events.append(
                event_type=AgentEventType.MISSION_STARTED,
                aggregate_type="mission",
                aggregate_id=mission.id,
                mission_id=mission.id,
                order_id=order.id,
                vehicle_id=vehicle.id,
            )
        if state.status in (VehicleStatus.TO_PICKUP, VehicleStatus.LOADING):
            order.status = OrderStatus.PICKING.value
        elif state.carrying_cargo or state.status in (
            VehicleStatus.TO_DROPOFF,
            VehicleStatus.UNLOADING,
        ):
            order.status = OrderStatus.IN_TRANSIT.value
        self.events.append(
            event_type=AgentEventType.VEHICLE_POSITION_UPDATED,
            aggregate_type="vehicle",
            aggregate_id=vehicle.id,
            mission_id=mission.id,
            order_id=order.id,
            vehicle_id=vehicle.id,
            payload={
                "node_id": state.node_id,
                "phase": state.phase,
                "cursor": cursor,
                "carrying_cargo": state.carrying_cargo,
            },
        )

    def _complete(
        self, state: VehicleRuntimeState, command_id: str, timestamp: datetime
    ) -> None:
        mission = MissionRepository(self.session).complete(
            state.mission_id, completed_at=timestamp
        )
        if not mission:
            return
        OrderRepository(self.session).mark_delivered(mission.order_id)
        VehicleRepository(self.session).finish_mission(
            self.vehicle_id,
            node_id=state.node_id,
            heading=state.heading,
            telemetry_updated_at=timestamp,
        )
        self.reservations.release(mission.id)
        self.commands.complete(command_id)
        agent_state = self.session.get(VehicleAgentStateRecord, self.vehicle_id)
        agent_state.status = AgentStatus.READY.value
        agent_state.active_command_id = None
        agent_state.active_mission_id = None
        agent_state.execution_cursor = 0
        agent_state.carrying_cargo = False
        self.events.append(
            event_type=AgentEventType.MISSION_COMPLETED,
            aggregate_type="mission",
            aggregate_id=mission.id,
            mission_id=mission.id,
            order_id=mission.order_id,
            vehicle_id=self.vehicle_id,
            payload={"final_node_id": state.node_id},
        )
        self._complete_batch_if_ready(mission.order_id)

    def _complete_batch_if_ready(self, order_id: str) -> None:
        order = self.session.get(TransportOrderRecord, order_id)
        if not order or not order.batch_id:
            return
        statuses = list(
            self.session.scalars(
                select(TransportOrderRecord.status).where(
                    TransportOrderRecord.batch_id == order.batch_id
                )
            )
        )
        batch = self.session.get(TransportBatchRecord, order.batch_id)
        if batch and statuses and all(status == OrderStatus.DELIVERED.value for status in statuses):
            batch.status = BatchStatus.COMPLETED.value
        elif batch:
            batch.status = BatchStatus.RUNNING.value

    def _idle_state(self) -> VehicleRuntimeState:
        vehicle = self.session.get(VehicleRecord, self.vehicle_id)
        return VehicleRuntimeState(
            vehicle_id=vehicle.id,
            node_id=vehicle.current_node_id,
            heading=vehicle.heading,
            status=VehicleStatus(vehicle.status),
            phase="等待任务",
            mission_id=None,
            order_id=None,
            cargo_name=None,
            carrying_cargo=False,
            executed_node_ids=(vehicle.current_node_id,),
            remaining_node_ids=(),
        )

    def _ensure_state(self) -> None:
        if self.session.get(VehicleAgentStateRecord, self.vehicle_id):
            return
        self.session.add(
            VehicleAgentStateRecord(
                vehicle_id=self.vehicle_id,
                agent_id=self.agent_id,
                status=AgentStatus.READY.value,
            )
        )
        self.session.flush()


def _deserialize_state(value: object) -> VehicleRuntimeState:
    if not isinstance(value, dict):
        raise ValueError("vehicle execution state must be an object")
    return VehicleRuntimeState(
        vehicle_id=str(value["vehicle_id"]),
        node_id=str(value["node_id"]),
        heading=float(value["heading"]),
        status=VehicleStatus(str(value["status"])),
        phase=str(value["phase"]),
        mission_id=str(value["mission_id"]),
        order_id=str(value["order_id"]),
        cargo_name=str(value["cargo_name"]) if value.get("cargo_name") else None,
        carrying_cargo=bool(value["carrying_cargo"]),
        executed_node_ids=tuple(str(item) for item in value["executed_node_ids"]),
        remaining_node_ids=tuple(str(item) for item in value["remaining_node_ids"]),
    )
