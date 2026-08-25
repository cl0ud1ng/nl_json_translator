import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from nl_json_translator.domain.enums import MissionStepType, OrderStatus, VehicleStatus
from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import (
    AgentEventRecord,
    MissionRecord,
    TransportOrderRecord,
    VehicleRecord,
)
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.services.dispatch_service import DispatchService


class DispatchServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{Path(self.temp_dir.name) / 'dispatch.db'}"
        seed_demo_data(self.url)
        self.database = Database(self.url)

    def tearDown(self):
        self.database.dispose()
        self.temp_dir.cleanup()

    def _add_order(
        self,
        order_id: str,
        *,
        pickup: str = "loc_c",
        dropoff: str = "loc_a",
        cargo=None,
        priority: str = "normal",
        requested_vehicle_id=None,
    ):
        with self.database.session() as session:
            session.add(
                TransportOrderRecord(
                    id=order_id,
                    pickup_location_id=pickup,
                    dropoff_location_id=dropoff,
                    cargo_json=cargo or {"name": "周转箱", "quantity": 1, "weight_kg": 20},
                    priority=priority,
                    status=OrderStatus.RESOLVED.value,
                    requested_vehicle_id=requested_vehicle_id,
                )
            )

    def test_assigns_best_vehicle_and_creates_steps_and_events(self):
        self._add_order("order_near_c")

        with self.database.session() as session:
            result = DispatchService(session).dispatch_order("order_near_c")

            self.assertTrue(result.assigned)
            self.assertEqual(result.selected_vehicle_id, "vehicle_demo_02")
            self.assertEqual(
                [step.step_type for step in result.mission.steps],
                [
                    MissionStepType.REPOSITION,
                    MissionStepType.LOAD,
                    MissionStepType.TRANSPORT,
                    MissionStepType.UNLOAD,
                    MissionStepType.COMPLETE,
                ],
            )
            self.assertEqual(
                result.mission.steps[0].details["planned_node_ids"][0], "node_6_11"
            )

        with self.database.session() as session:
            order = session.get(TransportOrderRecord, "order_near_c")
            vehicle = session.get(VehicleRecord, "vehicle_demo_02")
            self.assertEqual(order.status, OrderStatus.ASSIGNED.value)
            self.assertEqual(vehicle.status, VehicleStatus.RESERVED.value)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(MissionRecord)), 1
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(AgentEventRecord)), 3
            )

    def test_filters_candidates_by_capability_and_capacity(self):
        self._add_order(
            "order_cold",
            pickup="loc_a",
            dropoff="loc_b",
            cargo={
                "name": "冷链药品",
                "quantity": 1,
                "weight_kg": 400,
                "volume_m3": 1,
                "required_capabilities": ["cold_chain"],
            },
        )

        with self.database.session() as session:
            result = DispatchService(session).dispatch_order("order_cold")

        self.assertEqual(result.selected_vehicle_id, "vehicle_demo_01")
        evaluations = {item.vehicle_id: item for item in result.candidates}
        self.assertIn("weight_capacity_exceeded", evaluations["vehicle_demo_02"].reasons)
        self.assertIn("missing_capabilities", evaluations["vehicle_demo_03"].reasons)

    def test_no_eligible_vehicle_leaves_order_resolved(self):
        self._add_order(
            "order_too_heavy",
            cargo={"name": "超重设备", "quantity": 1, "weight_kg": 5000},
        )

        with self.database.session() as session:
            result = DispatchService(session).dispatch_order("order_too_heavy")
            self.assertFalse(result.assigned)

        with self.database.session() as session:
            order = session.get(TransportOrderRecord, "order_too_heavy")
            self.assertEqual(order.status, OrderStatus.RESOLVED.value)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(MissionRecord)), 0
            )

    def test_dispatch_next_prioritizes_urgent_ready_order(self):
        self._add_order("order_normal", priority="normal")
        self._add_order("order_urgent", pickup="loc_b", dropoff="loc_a", priority="urgent")

        with self.database.session() as session:
            result = DispatchService(session).dispatch_next()

        self.assertEqual(result.order_id, "order_urgent")

    def test_dispatch_all_ready_assigns_distinct_vehicles(self):
        self._add_order("order_from_a", pickup="loc_a", dropoff="loc_b")
        self._add_order("order_from_c", pickup="loc_c", dropoff="loc_a")

        with self.database.session() as session:
            results = DispatchService(session).dispatch_all_ready()

        assigned = [result for result in results if result.assigned]
        self.assertEqual(len(assigned), 2)
        self.assertEqual(len({result.selected_vehicle_id for result in assigned}), 2)

    def test_rejects_stale_telemetry(self):
        self._add_order(
            "order_vehicle_01",
            pickup="loc_a",
            dropoff="loc_b",
            requested_vehicle_id="vehicle_demo_01",
        )
        now = datetime.now(timezone.utc)
        with self.database.session() as session:
            vehicle = session.get(VehicleRecord, "vehicle_demo_01")
            vehicle.telemetry_updated_at = now - timedelta(hours=1)

        with self.database.session() as session:
            result = DispatchService(session).dispatch_order("order_vehicle_01", now=now)

        self.assertFalse(result.assigned)
        requested = next(
            item for item in result.candidates if item.vehicle_id == "vehicle_demo_01"
        )
        self.assertIn("telemetry_stale", requested.reasons)


if __name__ == "__main__":
    unittest.main()
