import json
import unittest

from nl_json_translator.translator import Translator


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        return self.responses.pop(0)


class TranslatorTests(unittest.TestCase):
    def test_translates_valid_response(self):
        expected = {
            "action": "go_to_goal",
            "params": {"location": {"type": "str", "value": "B"}},
        }
        translator = Translator(FakeClient([json.dumps(expected)]))

        result = translator.translate("go to B")

        self.assertEqual(result.command, expected)
        self.assertEqual(result.attempts, 1)

    def test_retries_once_after_validation_error(self):
        valid = {
            "action": "stop",
            "params": {},
        }
        client = FakeClient(
            [
                '{"action":"plan_route","params":{"target":"B"}}',
                json.dumps(valid),
            ]
        )
        translator = Translator(client, retries=1)

        result = translator.translate("plan route to B")

        self.assertEqual(result.command, valid)
        self.assertEqual(result.attempts, 2)
        self.assertIn("failed validation", client.messages[1][1]["content"])


if __name__ == "__main__":
    unittest.main()

