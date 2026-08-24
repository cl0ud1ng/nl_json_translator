import tempfile
import unittest
from pathlib import Path

from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import LocationRecord
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.map_executor import build_runtime_frames, execute_command
from nl_json_translator.repositories.maps import MapRepository


class MapExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        url = f"sqlite:///{Path(self.temp_dir.name) / 'map.db'}"
        seed_demo_data(url)
        self.database = Database(url)
        self.session = self.database.session_factory()
        self.repository = MapRepository(self.session)

    def tearDown(self):
        self.session.close()
        self.database.dispose()
        self.temp_dir.cleanup()

    def test_sequence_go_to_goal(self):
        command = {
            "action": "sequence",
            "params": [
                {
                    "action": "go_to_goal",
                    "params": {"location": {"type": "str", "value": "B"}},
                },
                {
                    "action": "go_to_goal",
                    "params": {"location": {"type": "str", "value": "A"}},
                },
            ],
        }

        result = execute_command(command, repository=self.repository)

        self.assertEqual(len(result["timeline"]), 2)
        self.assertEqual(result["final_pose"]["x"], 2)
        self.assertEqual(result["final_pose"]["y"], 2)
        self.assertIn("<svg", result["svg"])

    def test_sequence_runtime_frames_show_motion(self):
        command = {
            "action": "sequence",
            "params": [
                {
                    "action": "go_to_goal",
                    "params": {"location": {"type": "str", "value": "B"}},
                },
                {
                    "action": "go_to_goal",
                    "params": {"location": {"type": "str", "value": "A"}},
                },
            ],
        }

        frames = build_runtime_frames(command, repository=self.repository)

        self.assertGreater(len(frames), 2)
        self.assertEqual(frames[0]["action"], "start")
        self.assertEqual(frames[-1]["pose"]["x"], 2)
        self.assertEqual(frames[-1]["pose"]["y"], 2)
        self.assertIn("<svg", frames[-1]["svg"])

    def test_database_location_is_immediately_available_to_executor(self):
        with self.database.session() as session:
            session.add(
                LocationRecord(
                    id="loc_staging",
                    name="staging",
                    map_node_id="node_3_2",
                    metadata_json={"label": "Stage", "color": "#111827"},
                )
            )
        command = {
            "action": "go_to_goal",
            "params": {"location": {"type": "str", "value": "loc_staging"}},
        }

        result = execute_command(command, repository=self.repository)

        self.assertEqual(result["final_pose"]["x"], 3)
        self.assertEqual(result["final_pose"]["y"], 2)
        self.assertIn("Stage", result["svg"])


if __name__ == "__main__":
    unittest.main()
