import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import TransportOrderRecord, VehicleRecord
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data


class TransportModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{Path(self.temp_dir.name) / 'transport.db'}"
        seed_demo_data(self.url)
        self.database = Database(self.url)

    def tearDown(self):
        self.database.dispose()
        self.temp_dir.cleanup()

    def test_demo_vehicle_and_resolved_order_persist(self):
        with self.database.session() as session:
            vehicle = session.get(VehicleRecord, "vehicle_demo_01")
            self.assertIsNotNone(vehicle)
            self.assertEqual(vehicle.current_node_id, "node_2_2")
            self.assertEqual(vehicle.battery_level, 100.0)

            session.add(
                TransportOrderRecord(
                    id="order_01",
                    pickup_location_id="loc_a",
                    dropoff_location_id="loc_b",
                    cargo_json={"name": "零件箱", "quantity": 3, "weight_kg": 15},
                    requested_vehicle_id=vehicle.id,
                    idempotency_key="request-01",
                )
            )

        with self.database.session() as session:
            order = session.scalar(select(TransportOrderRecord))
            self.assertEqual(order.pickup_location.name, "A")
            self.assertEqual(order.dropoff_location.name, "B")
            self.assertEqual(order.requested_vehicle.name, "Demo Vehicle 01")

    def test_review_order_allows_unresolved_location_ids(self):
        with self.database.session() as session:
            session.add(
                TransportOrderRecord(
                    id="order_review",
                    pickup_location_text="装配区",
                    dropoff_location_text="B",
                    cargo_json={"name": "箱子", "quantity": 1},
                    status="NEEDS_REVIEW",
                )
            )

    def test_idempotency_key_is_unique(self):
        with self.assertRaises(IntegrityError):
            with self.database.session() as session:
                for order_id in ("order_a", "order_b"):
                    session.add(
                        TransportOrderRecord(
                            id=order_id,
                            pickup_location_id="loc_a",
                            dropoff_location_id="loc_b",
                            cargo_json={"name": "箱子", "quantity": 1},
                            idempotency_key="same-request",
                        )
                    )


if __name__ == "__main__":
    unittest.main()
