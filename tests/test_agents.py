import tempfile
import unittest
from pathlib import Path

from sqlalchemy import func, select

from nl_json_translator.agents import AgentRuntime, DispatcherAgent, VehicleAgent
from nl_json_translator.domain.enums import (
    AgentCommandStatus,
    AgentStatus,
    BatchStatus,
    MissionStatus,
    OrderStatus,
)
from nl_json_translator.domain.schemas import TransportRequestDraft
from nl_json_translator.fleet_renderer import (
    render_fleet_svg,
    retain_completed_route_states,
)
from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import (
    AgentCommandRecord,
    MissionRecord,
    RouteReservationRecord,
    TransportBatchRecord,
    TransportOrderRecord,
    VehicleAgentStateRecord,
)
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.repositories.maps import MapRepository
from nl_json_translator.services.fleet_simulation_service import find_runtime_conflicts


def three_order_request():
    return TransportRequestDraft.model_validate(
        {
            "intent": "create_transport_orders",
            "orders": [
                {
                    "cargo": {"name": "零件箱 A", "weight_kg": 25},
                    "pickup_location_text": "A",
                    "dropoff_location_text": "B",
                },
                {
                    "cargo": {"name": "零件箱 B", "weight_kg": 30},
                    "pickup_location_text": "C",
                    "dropoff_location_text": "lab",
                },
                {
                    "cargo": {"name": "零件箱 C", "weight_kg": 35},
                    "pickup_location_text": "A",
                    "dropoff_location_text": "lab",
                },
            ],
            "dispatch_constraints": {"distinct_vehicle_per_order": True},
        }
    )


class TwoLevelAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{Path(self.temp_dir.name) / 'agents.db'}"
        seed_demo_data(self.url)
        self.database = Database(self.url)

    def tearDown(self):
        self.database.dispose()
        self.temp_dir.cleanup()

    def test_dispatcher_and_vehicle_agents_complete_generic_batch(self):
        with self.database.session() as session:
            submission = DispatcherAgent(session).submit(
                three_order_request(),
                natural_language="three independent orders",
                provider_response_id="chat-e2e",
                provider_model="deepseek-v4-pro",
                provider_usage={"total_tokens": 100},
            )
            self.assertEqual(len(submission.orders), 3)
            self.assertEqual(len({item.selected_vehicle_id for item in submission.dispatches}), 3)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(AgentCommandRecord)), 3
            )
            self.assertGreater(
                session.scalar(select(func.count()).select_from(RouteReservationRecord)),
                3,
            )
            simulation = AgentRuntime(session).run_until_idle()
            map_data = MapRepository(session).load()
            conflicts = find_runtime_conflicts(map_data, simulation)
            self.assertEqual(conflicts, [])
            final_route_frame = retain_completed_route_states(
                simulation, simulation.frames[-1]
            )
            self.assertEqual(
                sum(state.mission_id is not None for state in final_route_frame.vehicles),
                3,
            )
            final_svg = render_fleet_svg(
                map_data,
                simulation.snapshot,
                runtime_frame=final_route_frame,
            )
            self.assertEqual(final_svg.count('data-route-kind="executed"'), 3)

        with self.database.session() as session:
            self.assertTrue(
                all(
                    status == OrderStatus.DELIVERED.value
                    for status in session.scalars(select(TransportOrderRecord.status))
                )
            )
            self.assertTrue(
                all(
                    status == MissionStatus.COMPLETED.value
                    for status in session.scalars(select(MissionRecord.status))
                )
            )
            self.assertTrue(
                all(
                    status == AgentCommandStatus.COMPLETED.value
                    for status in session.scalars(select(AgentCommandRecord.status))
                )
            )
            self.assertTrue(
                all(
                    status == AgentStatus.READY.value
                    for status in session.scalars(select(VehicleAgentStateRecord.status))
                )
            )
            self.assertFalse(
                any(session.scalars(select(RouteReservationRecord.active)))
            )
            batch = session.get(TransportBatchRecord, submission.batch_id)
            self.assertEqual(batch.status, BatchStatus.COMPLETED.value)
            self.assertEqual(batch.provider_response_id, "chat-e2e")

    def test_vehicle_agent_recovers_from_persisted_cursor(self):
        with self.database.session() as session:
            request = TransportRequestDraft.model_validate(
                {
                    "intent": "create_transport_orders",
                    "orders": [
                        {
                            "cargo": {"name": "箱子"},
                            "pickup_location_text": "A",
                            "dropoff_location_text": "B",
                        }
                    ],
                }
            )
            submission = DispatcherAgent(session).submit(request)
            vehicle_id = submission.dispatches[0].selected_vehicle_id
            first = VehicleAgent(session, vehicle_id).tick(0)
            cursor = session.get(VehicleAgentStateRecord, vehicle_id).execution_cursor
            self.assertEqual(cursor, 1)

        with self.database.session() as session:
            second = VehicleAgent(session, vehicle_id).tick(1)
            self.assertNotEqual(
                (first.phase, first.executed_node_ids),
                (second.phase, second.executed_node_ids),
            )
            self.assertEqual(
                session.get(VehicleAgentStateRecord, vehicle_id).execution_cursor, 2
            )


if __name__ == "__main__":
    unittest.main()
