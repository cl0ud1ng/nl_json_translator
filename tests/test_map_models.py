import tempfile
import unittest
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.init_db import init_database
from nl_json_translator.infrastructure.orm_models import (
    LocationAliasRecord,
    LocationRecord,
    MapEdgeRecord,
    MapNodeRecord,
)


class MapModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database: Database = init_database(
            f"sqlite:///{Path(self.temp_dir.name) / 'models.db'}"
        )

    def tearDown(self):
        self.database.dispose()
        self.temp_dir.cleanup()

    def test_location_alias_and_edge_relationships_persist(self):
        with self.database.session() as session:
            node_a = MapNodeRecord(id="node_0_0", x=0, y=0)
            node_b = MapNodeRecord(id="node_1_0", x=1, y=0)
            location = LocationRecord(id="loc_a", name="A", map_node=node_a)
            location.aliases.append(
                LocationAliasRecord(alias="Alpha", normalized_alias="alpha")
            )
            session.add_all(
                [
                    location,
                    node_b,
                    MapEdgeRecord(
                        id="edge_0_0__1_0",
                        from_node=node_a,
                        to_node=node_b,
                        distance=1.0,
                        travel_time=1.0,
                    ),
                ]
            )

        with self.database.session() as session:
            stored = session.get(LocationRecord, "loc_a")
            self.assertIsNotNone(stored)
            self.assertEqual(stored.map_node.x, 0)
            self.assertEqual(stored.aliases[0].normalized_alias, "alpha")

    def test_duplicate_coordinates_are_rejected(self):
        with self.assertRaises(IntegrityError):
            with self.database.session() as session:
                session.add_all(
                    [
                        MapNodeRecord(id="node_one", x=2, y=3),
                        MapNodeRecord(id="node_two", x=2, y=3),
                    ]
                )


if __name__ == "__main__":
    unittest.main()
