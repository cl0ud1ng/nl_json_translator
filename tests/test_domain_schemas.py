import unittest

from pydantic import ValidationError

from nl_json_translator.domain.enums import OrderPriority
from nl_json_translator.domain.schemas import TransportIntentDraft, TransportOrder


class TransportIntentDraftTests(unittest.TestCase):
    def test_accepts_valid_transport_intent(self):
        draft = TransportIntentDraft.model_validate(
            {
                "intent": "create_transport_order",
                "cargo": {"name": "零件箱", "quantity": 3, "weight_kg": 15},
                "pickup_location_text": " 一号库 ",
                "dropoff_location_text": "装配区",
                "vehicle_text": None,
                "priority": "normal",
            }
        )

        self.assertEqual(draft.pickup_location_text, "一号库")
        self.assertEqual(draft.priority, OrderPriority.NORMAL)

    def test_rejects_same_pickup_and_dropoff(self):
        with self.assertRaises(ValidationError):
            TransportIntentDraft.model_validate(
                {
                    "intent": "create_transport_order",
                    "cargo": {"name": "零件", "quantity": 1},
                    "pickup_location_text": "A",
                    "dropoff_location_text": "a",
                }
            )


class TransportOrderTests(unittest.TestCase):
    def test_accepts_resolved_order(self):
        order = TransportOrder.model_validate(
            {
                "type": "transport_order",
                "cargo": {"name": "零件箱", "quantity": 3, "weight_kg": 15},
                "pickup_location_id": "loc_warehouse_01",
                "dropoff_location_id": "loc_assembly_02",
                "requested_vehicle_id": None,
                "priority": "high",
            }
        )

        self.assertEqual(order.priority, OrderPriority.HIGH)

    def test_rejects_invalid_cargo_and_unknown_fields(self):
        with self.assertRaises(ValidationError):
            TransportOrder.model_validate(
                {
                    "cargo": {"name": "", "quantity": 0},
                    "pickup_location_id": "loc_a",
                    "dropoff_location_id": "loc_b",
                    "made_up": True,
                }
            )


if __name__ == "__main__":
    unittest.main()
