import tempfile
import unittest
from pathlib import Path

from sqlalchemy import func, select

from nl_json_translator.domain.enums import OrderStatus, VehicleStatus
from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import (
    MissionRecord,
    TransportOrderRecord,
    VehicleRecord,
)
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.services.demo_scenario_service import DemoScenarioService
from nl_json_translator.services.fleet_simulation_service import (
    find_runtime_conflicts,
)


class DemoScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{Path(self.temp_dir.name) / 'scenario.db'}"
        seed_demo_data(self.url)
        self.database = Database(self.url)

    def tearDown(self):
        self.database.dispose()
        self.temp_dir.cleanup()

    def test_creates_two_vehicle_missions_from_two_pickups_and_two_dropoffs(self):
        with self.database.session() as session:
            result = DemoScenarioService(session).create_two_vehicle_scenario(
                pickup_location_texts=("A", "C"),
                dropoff_location_texts=("B", "lab"),
            )
            map_data = MapRepository(session).load()
            conflicts = find_runtime_conflicts(map_data, result.simulation)

            self.assertEqual(len(result.orders), 2)
            self.assertEqual(len(result.dispatches), 2)
            self.assertEqual(len(result.simulation.mission_ids), 2)
            self.assertEqual(
                len({item.selected_vehicle_id for item in result.dispatches}), 2
            )
            self.assertEqual(conflicts, [])

        with self.database.session() as session:
            orders = list(
                session.scalars(
                    select(TransportOrderRecord).where(
                        TransportOrderRecord.batch_id == result.batch_id
                    )
                )
            )
            self.assertEqual(len(orders), 2)
            self.assertEqual(len({order.pickup_location_id for order in orders}), 2)
            self.assertEqual(len({order.dropoff_location_id for order in orders}), 2)
            self.assertTrue(
                all(order.status == OrderStatus.ASSIGNED.value for order in orders)
            )
            missions = list(session.scalars(select(MissionRecord)))
            self.assertEqual(len({mission.vehicle_id for mission in missions}), 2)

    def test_reset_removes_runtime_records_and_restores_two_idle_vehicles(self):
        with self.database.session() as session:
            DemoScenarioService(session).create_two_vehicle_scenario(
                pickup_location_texts=("A", "C"),
                dropoff_location_texts=("B", "lab"),
            )

        with self.database.session() as session:
            session.add(VehicleRecord(
                id="vehicle_demo_03", name="Demo Vehicle 03",
                current_node_id="node_17_11", status="IDLE",
                capacity_weight=1000.0, capacity_volume=6.0,
                battery_level=62.0, capabilities=["standard"],
            ))

        with self.database.session() as session:
            reset = DemoScenarioService(session).reset_demo_runtime()
            self.assertEqual(reset["missions"], 2)
            self.assertEqual(reset["orders"], 2)

        with self.database.session() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(MissionRecord)), 0
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(TransportOrderRecord)), 0
            )
            vehicles = list(session.scalars(select(VehicleRecord).order_by(VehicleRecord.id)))
            self.assertEqual(len(vehicles), 2)
            self.assertTrue(
                all(vehicle.status == VehicleStatus.IDLE.value for vehicle in vehicles)
            )
            self.assertEqual(
                [vehicle.current_node_id for vehicle in vehicles],
                ["node_2_2", "node_6_11"],
            )

    def test_rejects_duplicate_pickup_or_dropoff_locations(self):
        with self.database.session() as session:
            service = DemoScenarioService(session)
            with self.assertRaisesRegex(ValueError, "取货地点"):
                service.create_two_vehicle_scenario(
                    pickup_location_texts=("A", "A"),
                    dropoff_location_texts=("B", "lab"),
                )


if __name__ == "__main__":
    unittest.main()
