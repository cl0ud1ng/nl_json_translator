import unittest

from pydantic import ValidationError

from nl_json_translator.domain.enums import OrderPriority
from nl_json_translator.domain.schemas import (
    TransportOrder,
    TransportOrderDraft,
    TransportRequestDraft,
)


class TransportRequestDraftTests(unittest.TestCase):
    def test_accepts_multiple_orders(self):
        request = TransportRequestDraft.model_validate(
            {
                "intent": "create_transport_orders",
                "orders": [
                    {
                        "cargo": {"name": "零件箱", "quantity": 3},
                        "pickup_location_text": " A ",
                        "dropoff_location_text": "B",
                    },
                    {
                        "cargo": {"name": "药品", "quantity": 1},
                        "pickup_location_text": "lab",
                        "dropoff_location_text": "charging station",
                        "priority": "urgent",
                    },
                ],
                "dispatch_constraints": {"distinct_vehicle_per_order": True},
            }
        )

        self.assertEqual(request.orders[0].pickup_location_text, "A")
        self.assertEqual(request.orders[1].priority, OrderPriority.URGENT)
        self.assertTrue(request.dispatch_constraints.distinct_vehicle_per_order)

    def test_rejects_empty_batch_and_same_locations(self):
        with self.assertRaises(ValidationError):
            TransportRequestDraft.model_validate(
                {"intent": "create_transport_orders", "orders": []}
            )
        with self.assertRaises(ValidationError):
            TransportOrderDraft.model_validate(
                {
                    "cargo": {"name": "零件"},
                    "pickup_location_text": "A",
                    "dropoff_location_text": "a",
                }
            )


class TransportOrderTests(unittest.TestCase):
    def test_accepts_resolved_order(self):
        order = TransportOrder.model_validate(
            {
                "cargo": {"name": "零件箱", "quantity": 3, "weight_kg": 15},
                "pickup_location_id": "loc_warehouse_01",
                "dropoff_location_id": "loc_assembly_02",
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
