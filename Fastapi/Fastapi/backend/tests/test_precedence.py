"""Ordered precedence and the seven checks.

The rule that matters most is number three sitting above number four. A batch
under advisory that also carries expired evidence must return `hold`, not
`allow_with_warning`. That ordering is what replaced the two-of-three consensus
vote the client withdrew on 22 July 2026.
"""

import unittest

from ramify.ratify import precedence
from ramify.ratify.checks import (
    FAIL,
    HARD_STOP,
    INCOMPLETE,
    INCOMPLETE_SEVERITY,
    INFORMATIONAL,
    PASS,
    POLICY_DEPENDENT,
    REVIEW,
    CheckResult,
)


def check(outcome, severity=INFORMATIONAL, check_id="synthetic", codes=None):
    return CheckResult(check_id, check_id, outcome, severity, "", codes or [])


class TestPrecedenceRules(unittest.TestCase):
    def test_rule_1_recall_blocks(self):
        outcome = precedence.evaluate([check(PASS)], "recalled")
        self.assertEqual(outcome.posture, "block")
        self.assertEqual(outcome.matched_rule, 1)

    def test_rule_2_hard_stop_failure_blocks(self):
        outcome = precedence.evaluate([check(FAIL, HARD_STOP)], "no_active_recall")
        self.assertEqual(outcome.posture, "block")
        self.assertEqual(outcome.matched_rule, 2)

    def test_rule_3_advisory_holds(self):
        outcome = precedence.evaluate([check(PASS)], "advisory")
        self.assertEqual(outcome.posture, "hold")
        self.assertEqual(outcome.matched_rule, 3)

    def test_rule_4_review_warns(self):
        outcome = precedence.evaluate(
            [check(PASS), check(REVIEW, POLICY_DEPENDENT)], "no_active_recall"
        )
        self.assertEqual(outcome.posture, "allow_with_warning")
        self.assertEqual(outcome.matched_rule, 4)

    def test_rule_5_all_clear_allows(self):
        outcome = precedence.evaluate([check(PASS), check(PASS)], "no_active_recall")
        self.assertEqual(outcome.posture, "allow")
        self.assertEqual(outcome.matched_rule, 5)

    def test_rule_6_incomplete_escalates(self):
        outcome = precedence.evaluate(
            [check(INCOMPLETE, INCOMPLETE_SEVERITY)], "no_active_recall"
        )
        self.assertEqual(outcome.posture, "escalate")
        self.assertEqual(outcome.matched_rule, 6)

    def test_advisory_outranks_expired_evidence(self):
        outcome = precedence.evaluate(
            [check(REVIEW, POLICY_DEPENDENT, "evidence_freshness", ["evidence_expired"])],
            "advisory",
        )
        self.assertEqual(outcome.posture, "hold")

    def test_recall_outranks_everything(self):
        outcome = precedence.evaluate([check(PASS)] * 7, "recalled")
        self.assertEqual(outcome.posture, "block")

    def test_incomplete_never_reaches_an_approving_posture(self):
        # Missing evidence must not fall through to allow. This is the defect
        # that let the Sprint 1 build return `approved` for an unknown product.
        for standing in ("no_active_recall", "unknown"):
            with self.subTest(standing=standing):
                outcome = precedence.evaluate(
                    [check(PASS), check(INCOMPLETE, INCOMPLETE_SEVERITY)], standing
                )
                self.assertIn(outcome.posture, ("escalate", "block", "hold"))
                self.assertNotIn(outcome.posture, ("allow", "allow_with_warning"))

    def test_every_matched_condition_is_recorded(self):
        # Not only the winning one. Reason codes below the winning precedence
        # still belong in the receipt for audit.
        checks = [
            check(REVIEW, POLICY_DEPENDENT, "evidence_freshness", ["evidence_expired"]),
            check(REVIEW, POLICY_DEPENDENT, "seller_authority", ["seller_authority_unverified_for_category"]),
        ]
        outcome = precedence.evaluate(checks, "advisory")
        self.assertEqual(outcome.posture, "hold")
        self.assertIn("evidence_expired", outcome.reason_codes)
        self.assertIn("seller_authority_unverified_for_category", outcome.reason_codes)

    def test_lower_precedence_matches_are_kept(self):
        outcome = precedence.evaluate([check(FAIL, HARD_STOP)], "recalled")
        rules = [m["rule"] for m in outcome.matched_conditions]
        self.assertEqual(outcome.matched_rule, 1)
        self.assertIn(2, rules)

    def test_five_postures_exist_and_no_more(self):
        # Amendment v0.4.1 item 4: five action postures, six precedence rules.
        self.assertEqual(len(precedence.RESTRICTIVENESS), 5)
        self.assertEqual(
            set(precedence.RESTRICTIVENESS),
            {"allow", "allow_with_warning", "hold", "escalate", "block"},
        )


class TestRestrictivenessOrdering(unittest.TestCase):
    def test_block_is_the_most_restrictive(self):
        ranks = precedence.RESTRICTIVENESS
        self.assertEqual(max(ranks, key=ranks.get), "block")

    def test_allow_is_the_least_restrictive(self):
        ranks = precedence.RESTRICTIVENESS
        self.assertEqual(min(ranks, key=ranks.get), "allow")

    def test_narrowing_direction(self):
        self.assertTrue(precedence.is_narrowing("allow", "hold"))
        self.assertTrue(precedence.is_narrowing("hold", "hold"))
        self.assertFalse(precedence.is_narrowing("block", "allow"))
        self.assertFalse(precedence.is_narrowing("hold", "allow_with_warning"))


if __name__ == "__main__":
    unittest.main()
