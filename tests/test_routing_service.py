import tempfile
import unittest
from pathlib import Path

from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import MapEdgeRecord
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.services.routing_service import RoutingService


class RoutingServiceTests(unittest.TestCase):
    def test_uses_persisted_edge_weights(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            url = f"sqlite:///{Path(temp_dir) / 'routing.db'}"
            seed_demo_data(url)
            database = Database(url)
            with database.session() as session:
                direct = session.get(MapEdgeRecord, "edge_2_2__3_2")
                direct.distance = 100.0

            with database.session() as session:
                map_data = MapRepository(session).load()
                route = RoutingService().shortest_route(
                    map_data, "node_2_2", "node_3_2"
                )

            self.assertIsNotNone(route)
            self.assertEqual(route.distance, 3.0)
            self.assertNotEqual(route.node_ids, ("node_2_2", "node_3_2"))
            database.dispose()


if __name__ == "__main__":
    unittest.main()
