import json
import unittest
from pathlib import Path

from nl_json_translator.schema import validate_transport_intent


class SampleFixtureTests(unittest.TestCase):
    def test_transport_intent_samples_are_schema_valid(self):
        fixture = Path(__file__).resolve().parents[1] / "samples" / "transport_orders.jsonl"
        for line_number, line in enumerate(fixture.read_text(encoding="utf-8").splitlines(), start=1):
            with self.subTest(line=line_number):
                row = json.loads(line)
                intent = validate_transport_intent(row["expected"])
                self.assertEqual(intent["intent"], "create_transport_order")


if __name__ == "__main__":
    unittest.main()
