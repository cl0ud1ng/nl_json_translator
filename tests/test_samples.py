import json
import unittest
from pathlib import Path

from nl_json_translator.schema import validate_command


class SampleFixtureTests(unittest.TestCase):
    def test_expected_sample_outputs_are_schema_valid(self):
        fixture = Path(__file__).resolve().parents[1] / "samples" / "commands_ground_robot.jsonl"
        for line_number, line in enumerate(fixture.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            with self.subTest(line=line_number):
                row = json.loads(line)
                validate_command(row["expected"])


if __name__ == "__main__":
    unittest.main()

