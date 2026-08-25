from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import AgentCommandStatus
from nl_json_translator.infrastructure.orm_models import AgentCommandRecord
from nl_json_translator.services.fleet_simulation_service import (
    FleetRuntimeFrame,
    FleetSimulation,
)
from nl_json_translator.services.fleet_view_service import FleetViewService

from .vehicle import VehicleAgent


class AgentRuntime:
    """Deterministic virtual-clock runner for one Dispatcher and N vehicle agents."""

    def __init__(self, session: Session):
        self.session = session

    def run_until_idle(self, *, max_ticks: int = 1000) -> FleetSimulation:
        snapshot = FleetViewService(self.session).snapshot()
        mission_ids = tuple(mission.id for mission in snapshot.active_missions)
        agents = tuple(
            VehicleAgent(self.session, vehicle.id) for vehicle in snapshot.vehicles
        )
        frames: list[FleetRuntimeFrame] = []
        for time_slot in range(max_ticks):
            states = tuple(agent.tick(time_slot) for agent in agents)
            frames.append(FleetRuntimeFrame(index=time_slot, vehicles=states))
            if not self._has_work():
                break
        else:
            raise RuntimeError(f"agent runtime exceeded {max_ticks} ticks")
        return FleetSimulation(snapshot, tuple(frames), mission_ids)

    def _has_work(self) -> bool:
        count = self.session.scalar(
            select(AgentCommandRecord.id)
            .where(
                AgentCommandRecord.status.in_(
                    [
                        AgentCommandStatus.PENDING.value,
                        AgentCommandStatus.RUNNING.value,
                    ]
                )
            )
            .limit(1)
        )
        return count is not None
