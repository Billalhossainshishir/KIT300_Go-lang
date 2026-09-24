"""Regression checks for the David live verification demonstration."""

import unittest

from ramify.engine import escalation_for


class TestDavidDemoRegression(unittest.TestCase):
    def test_integrity_hard_stop_has_block_wording(self):
        result = escalation_for(["evidence_hash_mismatch"], "block")
        self.assertEqual(result["kind"], "integrity")
        self.assertFalse(result["requires_human"])
        self.assertIn("evidence integrity", result["headline"].lower())


if __name__ == "__main__":
    unittest.main()
