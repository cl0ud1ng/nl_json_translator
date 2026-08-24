import json
import unittest

from nl_json_translator.translator import Translator


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        return self.responses.pop(0)


class TranslatorTests(unittest.TestCase):
    def test_translates_valid_response(self):
        expected = {
            "intent": "create_transport_order",
            "cargo": {"name": "零件箱", "quantity": 3},
            "pickup_location_text": "A",
            "dropoff_location_text": "B",
            "vehicle_text": None,
            "priority": "normal",
        }
        translator = Translator(FakeClient([json.dumps(expected)]))

        result = translator.translate("从 A 取 3 箱零件送到 B")

        self.assertEqual(result.intent["pickup_location_text"], "A")
        self.assertEqual(result.intent["dropoff_location_text"], "B")
        self.assertEqual(result.intent["cargo"]["quantity"], 3)
        self.assertEqual(result.attempts, 1)

    def test_retries_once_after_validation_error(self):
        valid = {
            "intent": "create_transport_order",
            "cargo": {"name": "箱子", "quantity": 1},
            "pickup_location_text": "A",
            "dropoff_location_text": "B",
        }
        client = FakeClient(
            [
                '{"intent":"drive","pickup_location_text":"A"}',
                json.dumps(valid),
            ]
        )
        translator = Translator(client, retries=1)

        result = translator.translate("move a box from A to B")

        self.assertEqual(result.intent["intent"], "create_transport_order")
        self.assertEqual(result.attempts, 2)
        self.assertIn("failed validation", client.messages[1][1]["content"])


if __name__ == "__main__":
    unittest.main()
