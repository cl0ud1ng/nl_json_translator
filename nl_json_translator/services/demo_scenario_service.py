from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import VehicleStatus
from nl_json_translator.domain.location_text import normalize_location_text
from nl_json_translator.infrastructure.demo_map import DEMO_VEHICLES, node_id
from nl_json_translator.infrastructure.orm_models import (
    AgentEventRecord,
    MissionRecord,
    TransportOrderRecord,
    VehicleRecord,
)
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.repositories.missions import MissionRepository
from nl_json_translator.repositories.vehicles import VehicleRepository

from .dispatch_service import DispatchResult, DispatchService
from .fleet_simulation_service import FleetSimulation, FleetSimulationService
from .fleet_view_service import FleetViewService
from .order_service import OrderCreationResult, OrderService


class ScenarioStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ThreeVehicleScenarioResult:
    batch_id: str
    orders: tuple[OrderCreationResult, ...]
    dispatches: tuple[DispatchResult, ...]
    simulation: FleetSimulation


class DemoScenarioService:
    def __init__(self, session: Session):
        self.session = session

    def create_three_vehicle_scenario(
        self,
        *,
        pickup_location_texts: tuple[str, str],
        dropoff_location_texts: tuple[str, str],
        cargo_names: Sequence[str] = ("零件箱 A", "零件箱 B", "零件箱 C"),
    ) -> ThreeVehicleScenarioResult:
        self._validate_locations(pickup_location_texts, dropoff_location_texts)
        if len(cargo_names) != 3 or any(not name.strip() for name in cargo_names):
            raise ValueError("three non-empty cargo names are required")
        if MissionRepository(self.session).list_active():
            raise ScenarioStateError("请先完成或重置当前活动 Mission")
        idle_vehicles = [
            vehicle
            for vehicle in VehicleRepository(self.session).list_all()
            if vehicle.status is VehicleStatus.IDLE
        ]
        if len(idle_vehicles) < 3:
            raise ScenarioStateError("三车场景需要至少 3 辆空闲车辆")

        batch_id = f"batch_{uuid4().hex}"
        pairs = (
            (pickup_location_texts[0], dropoff_location_texts[0]),
            (pickup_location_texts[1], dropoff_location_texts[1]),
            (pickup_location_texts[0], dropoff_location_texts[1]),
        )
        order_service = OrderService(self.session)
        dispatch_service = DispatchService(self.session)
        orders: list[OrderCreationResult] = []
        dispatches: list[DispatchResult] = []
        for index, ((pickup, dropoff), cargo_name) in enumerate(
            zip(pairs, cargo_names),
            start=1,
        ):
            order = order_service.create_from_intent(
                {
                    "intent": "create_transport_order",
                    "cargo": {
                        "name": cargo_name,
                        "quantity": 1,
                        "weight_kg": 20 + index * 5,
                        "required_capabilities": [],
                    },
                    "pickup_location_text": pickup,
                    "dropoff_location_text": dropoff,
                    "priority": "normal",
                },
                idempotency_key=f"{batch_id}-{index}",
                batch_id=batch_id,
            )
            if not order.formal_order:
                raise ScenarioStateError(f"任务 {index} 的地点需要人工确认")
            dispatch = dispatch_service.dispatch_order(order.order_id)
            if not dispatch.assigned:
                reasons = sorted(
                    {
                        reason
                        for candidate in dispatch.candidates
                        for reason in candidate.reasons
                    }
                )
                raise ScenarioStateError(
                    f"任务 {index} 无可用车辆：{', '.join(reasons) or 'unknown'}"
                )
            orders.append(order)
            dispatches.append(dispatch)

        mission_ids = {
            dispatch.mission.id for dispatch in dispatches if dispatch.mission
        }
        snapshot = FleetViewService(self.session).snapshot()
        map_data = MapRepository(self.session).load()
        simulation = FleetSimulationService(self.session).build(
            map_data,
            snapshot,
            mission_ids=mission_ids,
        )
        if len(simulation.mission_ids) != 3:
            raise ScenarioStateError("三车场景未能创建 3 个独立 Mission")
        return ThreeVehicleScenarioResult(
            batch_id=batch_id,
            orders=tuple(orders),
            dispatches=tuple(dispatches),
            simulation=simulation,
        )

    def reset_demo_runtime(self) -> dict[str, int]:
        deleted_events = self.session.execute(delete(AgentEventRecord)).rowcount
        deleted_missions = self.session.execute(delete(MissionRecord)).rowcount
        deleted_orders = self.session.execute(delete(TransportOrderRecord)).rowcount
        timestamp = datetime.now(timezone.utc)
        reset_vehicles = 0
        for definition in DEMO_VEHICLES:
            vehicle = self.session.get(VehicleRecord, definition["id"])
            if not vehicle:
                continue
            x, y = definition["coordinate"]
            vehicle.current_node_id = node_id(x, y)
            vehicle.heading = definition["heading"]
            vehicle.status = VehicleStatus.IDLE.value
            vehicle.capacity_weight = definition["capacity_weight"]
            vehicle.capacity_volume = definition["capacity_volume"]
            vehicle.battery_level = definition["battery_level"]
            vehicle.capabilities = list(definition["capabilities"])
            vehicle.telemetry_updated_at = timestamp
            reset_vehicles += 1
        self.session.flush()
        return {
            "events": deleted_events,
            "missions": deleted_missions,
            "orders": deleted_orders,
            "vehicles": reset_vehicles,
        }

    @staticmethod
    def _validate_locations(
        pickups: tuple[str, str],
        dropoffs: tuple[str, str],
    ) -> None:
        normalized_pickups = tuple(normalize_location_text(value) for value in pickups)
        normalized_dropoffs = tuple(normalize_location_text(value) for value in dropoffs)
        if len(set(normalized_pickups)) != 2:
            raise ValueError("两个取货地点必须不同")
        if len(set(normalized_dropoffs)) != 2:
            raise ValueError("两个目标地点必须不同")
        pairs = (
            (normalized_pickups[0], normalized_dropoffs[0]),
            (normalized_pickups[1], normalized_dropoffs[1]),
            (normalized_pickups[0], normalized_dropoffs[1]),
        )
        if any(pickup == dropoff for pickup, dropoff in pairs):
            raise ValueError("每辆车的取货地点和目标地点必须不同")
