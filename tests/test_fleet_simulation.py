import tempfile
import unittest
from pathlib import Path

from nl_json_translator.domain.enums import MissionStatus, OrderStatus, VehicleStatus
from nl_json_translator.fleet_renderer import render_fleet_svg
from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import (
    AgentEventRecord,
    MissionRecord,
    TransportOrderRecord,
    VehicleRecord,
)
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.services.dispatch_service import DispatchService
from nl_json_translator.services.fleet_simulation_service import FleetSimulationService
from nl_json_translator.services.fleet_view_service import FleetViewService


class FleetSimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{Path(self.temp_dir.name) / 'simulation.db'}"
        seed_demo_data(self.url)
        self.database = Database(self.url)
        with self.database.session() as session:
            session.add_all(
                [
                    TransportOrderRecord(
                        id="order_a",
                        pickup_location_id="loc_a",
                        dropoff_location_id="loc_b",
                        cargo_json={"name": "A货物", "quantity": 1, "weight_kg": 20},
                        status=OrderStatus.RESOLVED.value,
                    ),
                    TransportOrderRecord(
                        id="order_c",
                        pickup_location_id="loc_c",
                        dropoff_location_id="loc_a",
                        cargo_json={"name": "C货物", "quantity": 1, "weight_kg": 20},
                        status=OrderStatus.RESOLVED.value,
                    ),
                ]
            )
        with self.database.session() as session:
            DispatchService(session).dispatch_all_ready()

    def tearDown(self):
        self.database.dispose()
        self.temp_dir.cleanup()

    def _simulation(self):
        session = self.database.session_factory()
        self.addCleanup(session.close)
        map_data = MapRepository(session).load()
        snapshot = FleetViewService(session).snapshot()
        simulation = FleetSimulationService(session).build(map_data, snapshot)
        return session, map_data, snapshot, simulation

    def test_builds_synchronized_pickup_transport_and_unload_frames(self):
        _, _, _, simulation = self._simulation()

        self.assertEqual(len(simulation.mission_ids), 2)
        self.assertGreater(len(simulation.frames), 10)
        states = [
            state
            for frame in simulation.frames
            for state in frame.vehicles
            if state.mission_id
        ]
        self.assertTrue(any(state.status is VehicleStatus.LOADING for state in states))
        self.assertTrue(any(state.status is VehicleStatus.TO_DROPOFF for state in states))
        self.assertTrue(any(state.status is VehicleStatus.UNLOADING for state in states))
        self.assertTrue(any(state.carrying_cargo for state in states))
        final_active = [
            state for state in simulation.frames[-1].vehicles if state.mission_id
        ]
        self.assertTrue(all(state.phase == "任务完成" for state in final_active))

    def test_runtime_svg_distinguishes_executed_and_remaining_routes(self):
        _, map_data, snapshot, simulation = self._simulation()
        middle = simulation.frames[len(simulation.frames) // 2]

        svg = render_fleet_svg(
            map_data,
            snapshot,
            runtime_frame=middle,
        )

        self.assertIn('data-route-kind="executed"', svg)
        self.assertIn('data-route-kind="remaining"', svg)
        self.assertIn("载货运输中", svg)
        self.assertIn(">货</text>", svg)

    def test_completion_persists_final_vehicle_order_and_mission_state(self):
        session, _, _, simulation = self._simulation()
        completed = FleetSimulationService(session).complete(simulation)
        session.commit()

        self.assertEqual(completed, 2)
        with self.database.session() as verification:
            missions = verification.query(MissionRecord).all()
            self.assertTrue(
                all(mission.status == MissionStatus.COMPLETED.value for mission in missions)
            )
            self.assertTrue(all(not mission.active for mission in missions))
            orders = verification.query(TransportOrderRecord).all()
            self.assertTrue(
                all(order.status == OrderStatus.DELIVERED.value for order in orders)
            )
            assigned_vehicle_ids = {mission.vehicle_id for mission in missions}
            vehicles = verification.query(VehicleRecord).filter(
                VehicleRecord.id.in_(assigned_vehicle_ids)
            )
            self.assertTrue(
                all(vehicle.status == VehicleStatus.IDLE.value for vehicle in vehicles)
            )
            completed_events = verification.query(AgentEventRecord).filter_by(
                event_type="MISSION_COMPLETED"
            )
            self.assertEqual(completed_events.count(), 2)


if __name__ == "__main__":
    unittest.main()
