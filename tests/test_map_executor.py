import unittest

from nl_json_translator.map_executor import build_runtime_frames, execute_command


class MapExecutorTests(unittest.TestCase):
    def test_sequence_go_to_goal(self):
        command = {
            "action": "sequence",
            "params": [
                {
                    "action": "go_to_goal",
                    "params": {"location": {"type": "str", "value": "B"}},
                },
                {
                    "action": "go_to_goal",
                    "params": {"location": {"type": "str", "value": "A"}},
                },
            ],
        }

        result = execute_command(command)

        self.assertEqual(len(result["timeline"]), 2)
        self.assertEqual(result["final_pose"]["x"], 2)
        self.assertEqual(result["final_pose"]["y"], 2)
        self.assertIn("<svg", result["svg"])

    def test_sequence_runtime_frames_show_motion(self):
        command = {
            "action": "sequence",
            "params": [
                {
                    "action": "go_to_goal",
                    "params": {"location": {"type": "str", "value": "B"}},
                },
                {
                    "action": "go_to_goal",
                    "params": {"location": {"type": "str", "value": "A"}},
                },
            ],
        }

        frames = build_runtime_frames(command)

        self.assertGreater(len(frames), 2)
        self.assertEqual(frames[0]["action"], "start")
        self.assertEqual(frames[-1]["pose"]["x"], 2)
        self.assertEqual(frames[-1]["pose"]["y"], 2)
        self.assertIn("<svg", frames[-1]["svg"])


if __name__ == "__main__":
    unittest.main()
