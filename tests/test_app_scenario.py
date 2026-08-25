import tempfile
import unittest
from pathlib import Path

from app import run_three_vehicle_scenario
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data


class AppScenarioTests(unittest.TestCase):
    def test_ui_adapter_builds_three_vehicle_dynamic_scenario(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            url = f"sqlite:///{Path(temp_dir) / 'app-scenario.db'}"
            seed_demo_data(url)

            result = run_three_vehicle_scenario(
                pickup_locations=("A", "C"),
                dropoff_locations=("B", "lab"),
                cargo_names=("货物一", "货物二", "货物三"),
                database_url=url,
            )

        self.assertTrue(result["validation"]["ok"])
        self.assertEqual(result["dispatch"]["assigned_count"], 3)
        self.assertEqual(len(result["order"]["orders"]), 3)
        self.assertEqual(len(result["fleet_simulation"].mission_ids), 3)


if __name__ == "__main__":
    unittest.main()
