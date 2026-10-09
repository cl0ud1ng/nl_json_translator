import tempfile
import unittest
from pathlib import Path

from nl_json_translator.agent_flow_renderer import render_agent_flow_svg
from nl_json_translator.agents import AgentRuntime, DispatcherAgent
from nl_json_translator.domain.schemas import TransportRequestDraft
from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data


class AgentFlowRendererTests(unittest.TestCase):
    def test_renders_bidirectional_messages_for_every_vehicle_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            url = f"sqlite:///{Path(temp_dir) / 'agent-flow.db'}"
            seed_demo_data(url)
            database = Database(url)
            try:
                with database.session() as session:
                    request = TransportRequestDraft.model_validate(
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
                            ],
                            "dispatch_constraints": {
                                "distinct_vehicle_per_order": True
                            },
                        }
                    )
                    DispatcherAgent(session).submit(request)
                    simulation = AgentRuntime(session).run_until_idle()
            finally:
                database.dispose()

        first = render_agent_flow_svg(simulation, simulation.frames[0])
        self.assertIn("DispatcherAgent", first)
        self.assertEqual(first.count('data-agent-id="vehicle/'), 2)
        self.assertEqual(first.count("AssignMission · Route v1"), 2)
        self.assertEqual(first.count("CommandAccepted"), 2)

        transport_frame = next(
            frame
            for frame in simulation.frames
            if any(state.phase == "载货运输中" for state in frame.vehicles)
        )
        transport = render_agent_flow_svg(simulation, transport_frame)
        self.assertIn("ExecuteStep · TRANSPORT", transport)
        self.assertIn("PositionUpdated", transport)

        final = render_agent_flow_svg(simulation, simulation.frames[-1])
        self.assertEqual(final.count("MissionCompleted"), 2)
        self.assertEqual(final.count("READY · COMPLETED"), 2)
        self.assertIn("执行中 0 · 已完成 2", final)

        focused = render_agent_flow_svg(
            simulation,
            transport_frame,
            selected_vehicle_id="vehicle_demo_01",
        )
        self.assertEqual(focused.count('opacity="0.25"'), 1)


if __name__ == "__main__":
    unittest.main()
