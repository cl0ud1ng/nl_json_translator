import unittest

from nl_json_translator.schema import CommandValidationError, validate_command


class SchemaTests(unittest.TestCase):
    def test_valid_sequence(self):
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

        self.assertEqual(validate_command(command), command)

    def test_rejects_unknown_action(self):
        with self.assertRaises(CommandValidationError):
            validate_command({"action": "plan_route", "params": {"target": "B"}})

    def test_rejects_move_with_distance_and_duration(self):
        command = {
            "action": "move",
            "params": {
                "linear_speed": 1.0,
                "distance": 1.0,
                "duration": 1.0,
                "is_forward": True,
                "unit": "meter",
            },
        }

        with self.assertRaises(CommandValidationError):
            validate_command(command)

    def test_valid_duration_move(self):
        command = {
            "action": "move",
            "params": {
                "linear_speed": 1.0,
                "duration": 2.0,
                "is_forward": False,
                "unit": "second",
            },
        }

        self.assertEqual(validate_command(command), command)


if __name__ == "__main__":
    unittest.main()

