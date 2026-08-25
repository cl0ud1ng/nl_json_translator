import json
import unittest

from nl_json_translator.deepseek_client import ChatCompletion
from nl_json_translator.translator import Translator


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        response = self.responses.pop(0)
        return response if isinstance(response, ChatCompletion) else ChatCompletion(response)


class TranslatorTests(unittest.TestCase):
    def test_translates_batch_response(self):
        expected = {
            "intent": "create_transport_orders",
            "orders": [
                {
                    "cargo": {"name": "零件箱 A", "quantity": 1},
                    "pickup_location_text": "A",
                    "dropoff_location_text": "B",
                },
                {
                    "cargo": {"name": "零件箱 B", "quantity": 1},
                    "pickup_location_text": "C",
                    "dropoff_location_text": "lab",
                },
            ],
            "dispatch_constraints": {"distinct_vehicle_per_order": True},
        }
        translator = Translator(FakeClient([json.dumps(expected)]))

        result = translator.translate("创建两张独立运输订单")

        self.assertEqual(len(result.request["orders"]), 2)
        self.assertTrue(result.request["dispatch_constraints"]["distinct_vehicle_per_order"])
        self.assertEqual(result.attempts, 1)

    def test_retries_once_after_validation_error(self):
        valid = {
            "intent": "create_transport_orders",
            "orders": [
                {
                    "cargo": {"name": "箱子", "quantity": 1},
                    "pickup_location_text": "A",
                    "dropoff_location_text": "B",
                }
            ],
        }
        client = FakeClient(['{"intent":"drive"}', json.dumps(valid)])
        result = Translator(client, retries=1).translate("move a box from A to B")

        self.assertEqual(result.request["intent"], "create_transport_orders")
        self.assertEqual(result.attempts, 2)
        self.assertIn("failed validation", client.messages[1][1]["content"])

    def test_preserves_provider_metadata(self):
        payload = {
            "intent": "create_transport_orders",
            "orders": [
                {
                    "cargo": {"name": "箱子"},
                    "pickup_location_text": "A",
                    "dropoff_location_text": "B",
                }
            ],
        }
        completion = ChatCompletion(
            json.dumps(payload),
            response_id="chat-1",
            model="deepseek-v4-pro",
            finish_reason="stop",
            usage={"total_tokens": 42},
        )

        result = Translator(FakeClient([completion])).translate("A 到 B")

        self.assertEqual(result.response_id, "chat-1")
        self.assertEqual(result.model, "deepseek-v4-pro")
        self.assertEqual(result.usage["total_tokens"], 42)


if __name__ == "__main__":
    unittest.main()
