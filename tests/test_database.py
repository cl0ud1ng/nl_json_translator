import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text

from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data


class DatabaseTests(unittest.TestCase):
    def test_sqlite_database_initializes_and_enables_foreign_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nested" / "demo.db"
            database = Database(f"sqlite:///{path}")
            database.create_schema()

            self.assertTrue(path.exists())
            self.assertEqual(
                inspect(database.engine).get_table_names(),
                ["location_aliases", "locations", "map_edges", "map_nodes"],
            )
            with database.session() as session:
                self.assertEqual(session.execute(text("PRAGMA foreign_keys")).scalar_one(), 1)
            database.dispose()

    def test_demo_seed_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            url = f"sqlite:///{Path(temp_dir) / 'demo.db'}"

            self.assertGreater(seed_demo_data(url), 0)
            self.assertEqual(seed_demo_data(url), 0)


if __name__ == "__main__":
    unittest.main()
