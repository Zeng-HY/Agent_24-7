import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import action_golden_fixtures


class ActionGoldenTests(unittest.TestCase):
    def test_action_outputs_match_the_recorded_bundle(self):
        expected = json.loads((HERE / "fixtures" / "action-golden.json").read_text(encoding="utf-8"))
        self.assertEqual(action_golden_fixtures.build(), expected)


if __name__ == "__main__":
    unittest.main()
