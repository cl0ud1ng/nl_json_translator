import tempfile
import unittest
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from nl_json_translator.domain.enums import AgentEventType, MissionStepType
from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import TransportOrderRecord, VehicleRecord
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.repositories.events import EventRepository
from nl_json_translator.repositories.missions import MissionRepository, MissionStepDefinition


class MissionModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{Path(self.temp_dir.name) / 'missions.db'}"
        seed_demo_data(self.url)
        self.database = Database(self.url)
        with self.database.session() as session:
            session.add(
                VehicleRecord(
                    id="vehicle_test_extra",
                    name="Test Extra Vehicle",
                    current_node_id="node_16_3",
                    capacity_weight=300,
                    capacity_volume=2,
                )
            )
            session.add_all(
                [
                    TransportOrderRecord(
                        id="order_01",
                        pickup_location_id="loc_a",
                        dropoff_location_id="loc_b",
                        cargo_json={"name": "零件箱", "quantity": 1},
                        status="RESOLVED",
                    ),
                    TransportOrderRecord(
                        id="order_02",
                        pickup_location_id="loc_b",
                        dropoff_location_id="loc_c",
                        cargo_json={"name": "周转箱", "quantity": 1},
                        status="RESOLVED",
                    ),
                ]
            )

    def tearDown(self):
        self.database.dispose()
        self.temp_dir.cleanup()

    def test_persists_ordered_steps_and_events(self):
        with self.database.session() as session:
            missions = MissionRepository(session)
            mission = missions.create(
                mission_id="mission_01",
                order_id="order_01",
                vehicle_id="vehicle_demo_01",
                steps=[
                    MissionStepDefinition(
                        MissionStepType.REPOSITION,
                        start_node_id="node_2_2",
                        end_node_id="node_2_2",
                    ),
                    MissionStepDefinition(
                        MissionStepType.TRANSPORT,
                        start_node_id="node_2_2",
                        end_node_id="node_16_3",
                    ),
                ],
            )
            EventRepository(session).append(
                event_type=AgentEventType.MISSION_CREATED,
                aggregate_type="mission",
                aggregate_id=mission.id,
                mission_id=mission.id,
                order_id=mission.order_id,
                vehicle_id=mission.vehicle_id,
                payload={"step_count": 2},
            )

        with self.database.session() as session:
            mission = MissionRepository(session).get("mission_01")
            self.assertEqual(
                [step.step_type for step in mission.steps],
                [MissionStepType.REPOSITION, MissionStepType.TRANSPORT],
            )
            events = EventRepository(session).list_for_mission("mission_01")
            self.assertEqual(events[0].event_type, AgentEventType.MISSION_CREATED.value)
            self.assertEqual(events[0].payload["step_count"], 2)

    def test_vehicle_and_order_allow_only_one_active_mission(self):
        step = MissionStepDefinition(MissionStepType.COMPLETE)
        with self.database.session() as session:
            MissionRepository(session).create(
                order_id="order_01",
                vehicle_id="vehicle_demo_01",
                steps=[step],
            )

        with self.assertRaises(IntegrityError):
            with self.database.session() as session:
                MissionRepository(session).create(
                    order_id="order_02",
                    vehicle_id="vehicle_demo_01",
                    steps=[step],
                )

        with self.assertRaises(IntegrityError):
            with self.database.session() as session:
                MissionRepository(session).create(
                    order_id="order_01",
                    vehicle_id="vehicle_test_extra",
                    steps=[step],
                )


if __name__ == "__main__":
    unittest.main()
