import os
import tempfile
import unittest
from pathlib import Path

from app import DEFAULT_REQUEST, ROOT_DIR, run_pipeline
from nl_json_translator.config import load_env_file
from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.services.fleet_simulation_service import find_runtime_conflicts


@unittest.skipUnless(
    os.getenv("RUN_DEEPSEEK_E2E") == "1",
    "set RUN_DEEPSEEK_E2E=1 to perform the paid network test",
)
class DeepSeekEndToEndTests(unittest.TestCase):
    def test_default_request_completes_real_multi_agent_pipeline(self):
        load_env_file(ROOT_DIR / ".env")
        self.assertTrue(os.getenv("DEEPSEEK_API_KEY", "").strip())
        previous_max_tokens = os.environ.get("DEEPSEEK_MAX_TOKENS")
        os.environ["DEEPSEEK_MAX_TOKENS"] = "2400"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                url = f"sqlite:///{Path(temp_dir) / 'deepseek-e2e.db'}"
                seed_demo_data(url)
                result = run_pipeline(
                    request_text=DEFAULT_REQUEST,
                    model="deepseek-v4-pro",
                    database_url=url,
                )
                simulation = result.get("fleet_simulation")
                database = Database(url)
                try:
                    with database.session() as session:
                        conflicts = (
                            find_runtime_conflicts(
                                MapRepository(session).load(), simulation
                            )
                            if simulation
                            else None
                        )
                finally:
                    database.dispose()
        finally:
            if previous_max_tokens is None:
                os.environ.pop("DEEPSEEK_MAX_TOKENS", None)
            else:
                os.environ["DEEPSEEK_MAX_TOKENS"] = previous_max_tokens

        translation = result.get("translation") or {}
        order = result.get("order") or {}
        orders = order.get("orders") or []
        dispatch = result.get("dispatch") or {}
        vehicle_ids = {
            item.get("selected_vehicle_id")
            for item in dispatch.get("results", [])
            if item.get("selected_vehicle_id")
        }
        self.assertTrue(result["validation"]["ok"], result["validation"])
        self.assertTrue(translation.get("response_id"))
        self.assertEqual(translation.get("provider_model"), "deepseek-v4-pro")
        self.assertEqual(len(orders), 3)
        self.assertEqual(order.get("status"), "DELIVERED")
        self.assertEqual(
            len({item["formal_order"]["pickup_location_id"] for item in orders}), 2
        )
        self.assertEqual(
            len({item["formal_order"]["dropoff_location_id"] for item in orders}), 2
        )
        self.assertEqual(dispatch.get("assigned_count"), 3)
        self.assertEqual(len(vehicle_ids), 3)
        self.assertEqual(len(simulation.mission_ids), 3)
        self.assertEqual(conflicts, [])


if __name__ == "__main__":
    unittest.main()
