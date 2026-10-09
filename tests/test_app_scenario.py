import json
import tempfile
import unittest
from pathlib import Path

from app import DEFAULT_REQUEST, run_pipeline
from nl_json_translator.deepseek_client import ChatCompletion
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.translator import Translator


class FakeDeepSeekClient:
    def complete(self, messages):
        del messages
        payload = {
            "intent": "create_transport_orders",
            "orders": [
                {
                    "cargo": {"name": "零件箱 A", "quantity": 1, "weight_kg": 25},
                    "pickup_location_text": "A",
                    "dropoff_location_text": "B",
                },
                {
                    "cargo": {"name": "零件箱 B", "quantity": 1, "weight_kg": 30},
                    "pickup_location_text": "C",
                    "dropoff_location_text": "lab",
                },
            ],
            "dispatch_constraints": {"distinct_vehicle_per_order": True},
        }
        return ChatCompletion(
            json.dumps(payload, ensure_ascii=False),
            response_id="chat-integration",
            model="deepseek-v4-pro",
            finish_reason="stop",
            usage={"total_tokens": 321},
        )


class AppScenarioTests(unittest.TestCase):
    def test_natural_language_adapter_runs_full_multi_agent_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            url = f"sqlite:///{Path(temp_dir) / 'app-scenario.db'}"
            seed_demo_data(url)
            result = run_pipeline(
                request_text=DEFAULT_REQUEST,
                model="deepseek-v4-pro",
                database_url=url,
                translator=Translator(FakeDeepSeekClient()),
            )

        self.assertTrue(result["validation"]["ok"])
        self.assertEqual(result["translation"]["response_id"], "chat-integration")
        self.assertEqual(result["dispatch"]["assigned_count"], 2)
        self.assertEqual(result["order"]["status"], "DELIVERED")
        orders = result["order"]["orders"]
        self.assertEqual(len(orders), 2)
        self.assertEqual(
            len({item["formal_order"]["pickup_location_id"] for item in orders}), 2
        )
        self.assertEqual(
            len({item["formal_order"]["dropoff_location_id"] for item in orders}), 2
        )
        self.assertEqual(len(result["fleet_simulation"].mission_ids), 2)


if __name__ == "__main__":
    unittest.main()
