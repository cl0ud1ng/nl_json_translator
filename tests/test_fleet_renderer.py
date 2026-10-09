import tempfile
import unittest
from pathlib import Path

from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import TransportOrderRecord, VehicleRecord
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.fleet_renderer import render_fleet_svg
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.services.dispatch_service import DispatchService
from nl_json_translator.services.fleet_simulation_service import FleetSimulationService
from nl_json_translator.services.fleet_view_service import FleetViewService


class FleetRendererTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{Path(self.temp_dir.name) / 'fleet.db'}"
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
                        status="RESOLVED",
                    ),
                    TransportOrderRecord(
                        id="order_c",
                        pickup_location_id="loc_c",
                        dropoff_location_id="loc_a",
                        cargo_json={"name": "C货物", "quantity": 1, "weight_kg": 20},
                        status="RESOLVED",
                    ),
                ]
            )
        with self.database.session() as session:
            DispatchService(session).dispatch_all_ready()

    def tearDown(self):
        self.database.dispose()
        self.temp_dir.cleanup()

    def test_snapshot_links_routes_to_multiple_vehicles(self):
        with self.database.session() as session:
            snapshot = FleetViewService(session).snapshot()
            map_data = MapRepository(session).load()
            svg = render_fleet_svg(
                map_data,
                snapshot,
                selected_vehicle_id="vehicle_demo_02",
                show_route_endpoints=True,
            )

        active = [vehicle for vehicle in snapshot.vehicles if vehicle.mission_id]
        self.assertEqual(len(active), 2)
        self.assertTrue(all(vehicle.planned_node_ids for vehicle in active))
        self.assertIn('aria-label="Multi-vehicle dispatch map"', svg)
        self.assertGreaterEqual(svg.count("stroke-dasharray"), 2)
        self.assertEqual(svg.count('data-route-endpoint="start"'), 2)
        self.assertEqual(svg.count('data-route-endpoint="end"'), 2)
        self.assertIn(">起</text>", svg)
        self.assertIn(">终</text>", svg)
        self.assertIn("Demo Vehicle 01", svg)
        self.assertIn("Demo Vehicle 02", svg)
        self.assertNotIn("Demo Vehicle 03", svg)

    def test_escapes_vehicle_labels(self):
        with self.database.session() as session:
            vehicle = session.get(VehicleRecord, "vehicle_demo_02")
            vehicle.name = "<Demo & Two>"

        with self.database.session() as session:
            snapshot = FleetViewService(session).snapshot()
            svg = render_fleet_svg(MapRepository(session).load(), snapshot)

        self.assertIn("&lt;Demo &amp; Two&gt;", svg)
        self.assertNotIn("<Demo & Two>", svg)

    def test_completed_fleet_keeps_last_planned_routes_and_endpoints(self):
        with self.database.session() as session:
            planned_snapshot = FleetViewService(session).snapshot()
            map_data = MapRepository(session).load()
            simulation = FleetSimulationService(session).build(
                map_data, planned_snapshot
            )
            FleetSimulationService(session).complete(simulation)

        with self.database.session() as session:
            current_snapshot = FleetViewService(session).snapshot()
            svg = render_fleet_svg(
                MapRepository(session).load(),
                current_snapshot,
                route_snapshot=planned_snapshot,
                show_route_endpoints=True,
            )

        self.assertFalse(any(vehicle.planned_node_ids for vehicle in current_snapshot.vehicles))
        self.assertEqual(svg.count('data-route-kind="planned"'), 2)
        self.assertEqual(svg.count('data-route-endpoint="start"'), 2)
        self.assertEqual(svg.count('data-route-endpoint="end"'), 2)


if __name__ == "__main__":
    unittest.main()
