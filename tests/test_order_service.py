import tempfile
import unittest
from pathlib import Path

from nl_json_translator.domain.enums import OrderStatus
from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import (
    LocationRecord,
    MapNodeRecord,
    TransportOrderRecord,
)
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.services.location_resolver import UnknownLocationError
from nl_json_translator.services.order_service import OrderService


class OrderServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{Path(self.temp_dir.name) / 'orders.db'}"
        seed_demo_data(self.url)
        self.database = Database(self.url)

    def tearDown(self):
        self.database.dispose()
        self.temp_dir.cleanup()

    @staticmethod
    def _intent(pickup="A", dropoff="B"):
        return {
            "intent": "create_transport_order",
            "cargo": {"name": "零件箱", "quantity": 3, "weight_kg": 15},
            "pickup_location_text": pickup,
            "dropoff_location_text": dropoff,
            "priority": "normal",
        }

    def test_resolves_and_persists_formal_order(self):
        with self.database.session() as session:
            result = OrderService(session).create_from_intent(
                self._intent(), idempotency_key="request-1"
            )

            self.assertEqual(result.status, OrderStatus.RESOLVED)
            self.assertEqual(result.formal_order.pickup_location_id, "loc_a")
            self.assertEqual(result.formal_order.dropoff_location_id, "loc_b")
            self.assertIsNotNone(session.get(TransportOrderRecord, result.order_id))

    def test_idempotency_returns_existing_order(self):
        with self.database.session() as session:
            service = OrderService(session)
            first = service.create_from_intent(self._intent(), idempotency_key="same")
            second = service.create_from_intent(self._intent(), idempotency_key="same")

            self.assertEqual(second.order_id, first.order_id)
            self.assertFalse(second.created)

    def test_ambiguous_location_creates_review_order(self):
        with self.database.session() as session:
            session.add_all(
                [
                    MapNodeRecord(id="node_assembly_east", x=40, y=40),
                    MapNodeRecord(id="node_assembly_west", x=40, y=41),
                    LocationRecord(
                        id="loc_assembly_east",
                        name="assembly east",
                        map_node_id="node_assembly_east",
                    ),
                    LocationRecord(
                        id="loc_assembly_west",
                        name="assembly west",
                        map_node_id="node_assembly_west",
                    ),
                ]
            )
            session.flush()
            service = OrderService(session)
            service.location_resolver.fuzzy_threshold = 0.65
            service.location_resolver.ambiguity_margin = 0.1
            result = service.create_from_intent(self._intent(pickup="assembly"))

            self.assertEqual(result.status, OrderStatus.NEEDS_REVIEW)
            self.assertIsNone(result.formal_order)

    def test_unknown_location_is_explicit_error(self):
        with self.database.session() as session:
            with self.assertRaises(UnknownLocationError):
                OrderService(session).create_from_intent(self._intent(pickup="火星基地"))


if __name__ == "__main__":
    unittest.main()
