import unittest

from pydantic import ValidationError

from nl_json_translator.schema import validate_transport_order, validate_transport_request


class PublicSchemaTests(unittest.TestCase):
    def test_validates_batch_request_as_only_external_intent(self):
        request = validate_transport_request(
            {
                "intent": "create_transport_orders",
                "orders": [
                    {
                        "cargo": {"name": "零件箱", "quantity": 3},
                        "pickup_location_text": "A",
                        "dropoff_location_text": "B",
                    }
                ],
            }
        )
        self.assertEqual(request["intent"], "create_transport_orders")

    def test_rejects_legacy_action_protocol(self):
        with self.assertRaises(ValidationError):
            validate_transport_request(
                {"action": "go_to_goal", "params": {"location": "B"}}
            )

    def test_validates_formal_resolved_order(self):
        order = validate_transport_order(
            {
                "cargo": {"name": "零件箱", "quantity": 3},
                "pickup_location_id": "loc_a",
                "dropoff_location_id": "loc_b",
            }
        )
        self.assertEqual(order["type"], "transport_order")


if __name__ == "__main__":
    unittest.main()
