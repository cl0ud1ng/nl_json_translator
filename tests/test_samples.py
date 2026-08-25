import json
import unittest
from pathlib import Path

from nl_json_translator.schema import validate_transport_request


class SampleFixtureTests(unittest.TestCase):
    def test_transport_intent_samples_are_schema_valid(self):
        fixture = Path(__file__).resolve().parents[1] / "samples" / "transport_orders.jsonl"
        for line_number, line in enumerate(fixture.read_text(encoding="utf-8").splitlines(), start=1):
            with self.subTest(line=line_number):
                row = json.loads(line)
                request = validate_transport_request(row["expected"])
                self.assertEqual(request["intent"], "create_transport_orders")


if __name__ == "__main__":
    unittest.main()
