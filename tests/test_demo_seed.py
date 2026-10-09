import tempfile
import unittest
from pathlib import Path

from sqlalchemy import func, select

from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.demo_map import (
    DEMO_GRID_HEIGHT,
    DEMO_GRID_WIDTH,
    DEMO_LOCATIONS,
    DEMO_OBSTACLE_COORDINATES,
    DEMO_VEHICLES,
    node_id,
)
from nl_json_translator.infrastructure.orm_models import (
    LocationRecord,
    MapEdgeRecord,
    MapNodeRecord,
    VehicleRecord,
)
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data


class DemoSeedTests(unittest.TestCase):
    def test_seed_migrates_static_map_and_locations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            url = f"sqlite:///{Path(temp_dir) / 'seed.db'}"
            inserted = seed_demo_data(url)
            self.assertGreater(inserted, 0)

            database = Database(url)
            with database.session() as session:
                node_count = session.scalar(select(func.count()).select_from(MapNodeRecord))
                edge_count = session.scalar(select(func.count()).select_from(MapEdgeRecord))
                locations = list(session.scalars(select(LocationRecord).order_by(LocationRecord.id)))
                vehicles = list(session.scalars(select(VehicleRecord).order_by(VehicleRecord.id)))

                self.assertEqual(
                    node_count,
                    DEMO_GRID_WIDTH * DEMO_GRID_HEIGHT - len(DEMO_OBSTACLE_COORDINATES),
                )
                self.assertGreater(edge_count, node_count)
                self.assertEqual(len(locations), len(DEMO_LOCATIONS))
                self.assertEqual({location.name for location in locations}, {"A", "B", "C", "lab", "charging station"})
                self.assertIsNone(session.get(MapNodeRecord, node_id(5, 2)))
                self.assertIsNotNone(session.get(MapNodeRecord, node_id(2, 2)))
                self.assertEqual(len(vehicles), len(DEMO_VEHICLES))
                self.assertEqual(
                    {vehicle.current_node_id for vehicle in vehicles},
                    {"node_2_2", "node_6_11"},
                )
            database.dispose()


if __name__ == "__main__":
    unittest.main()
