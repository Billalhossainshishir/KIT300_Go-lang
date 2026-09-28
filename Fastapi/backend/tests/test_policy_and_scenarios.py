"""Actor policy, the Action Gate, and the scenario oracles.

The load-bearing test here is `test_policy_never_widens`. Every scenario is run
against every profile and the result is compared against the restrictiveness
ordering. A policy bug that made a recalled product purchasable is exactly what
that test exists to catch.
"""

import unittest

from ramify.action import gate
from ramify.data import seed
from ramify.engine import assess
from ramify.policy import actor as actor_policy
from ramify.ratify.precedence import RESTRICTIVENESS


class TestScenarioOracles(unittest.TestCase):
    """Each scenario carries its expected result in the dataset.

    The engine must derive that result from the named checks rather than read
    it, so the expectation and the computation come from different places.
    """

    def test_every_scenario_matches_its_oracle(self):
        for scenario in seed.scenarios():
            with self.subTest(scenario=scenario["id"], note=scenario["note"]):
                result = assess(scenario["subject_ref"], scenario["actor"])
                self.assertEqual(
                    result["objective_posture"],
                    scenario["expected_objective"],
                    "objective posture",
                )
                self.assertEqual(
                    result["actor_decision"], scenario["expected_decision"], "actor decision"
                )

    def test_all_five_required_scenarios_are_covered(self):
        # Deliverable 1: approved, expired evidence, seller risk, active
        # recall, substitution.
        ids = " ".join(s["id"] for s in seed.scenarios())
        for required in ("APPROVED", "EXPIRED", "SELLER-RISK", "RECALL", "SUBSTITUTION"):
            self.assertIn(required, ids)


class TestPolicyNarrowsOnly(unittest.TestCase):
    def test_policy_never_widens(self):
        for subject_ref in seed.subjects():
            for actor_ref in seed.actor_profiles():
                with self.subTest(subject=subject_ref, actor=actor_ref):
                    result = assess(subject_ref, actor_ref)
                    self.assertGreaterEqual(
                        RESTRICTIVENESS[result["actor_decision"]],
                        RESTRICTIVENESS[result["objective_posture"]],
                        "an actor profile made the outcome more permissive",
                    )

    def test_objective_posture_is_identical_across_actors(self):
        for subject_ref in seed.subjects():
            with self.subTest(subject=subject_ref):
                postures = {
                    assess(subject_ref, actor_ref)["objective_posture"]
                    for actor_ref in seed.actor_profiles()
                }
                self.assertEqual(len(postures), 1, "objective assessment depends on the actor")

    def test_a_widening_rule_is_ignored_not_obeyed(self):
        decision = actor_policy.apply("block", "consumer_v1", None)
        self.assertEqual(decision.decision, "block")

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(KeyError):
            actor_policy.apply("allow", "no_such_profile", None)


class TestProofCase(unittest.TestCase):
    """One product, two actors, identical facts, different decisions."""

    SUBJECT = "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A"

    def test_objective_assessment_is_identical(self):
        consumer = assess(self.SUBJECT, "consumer_v1")["receipt"]
        procurement = assess(self.SUBJECT, "procurement_v1")["receipt"]
        self.assertEqual(consumer["objective_posture"], procurement["objective_posture"])
        self.assertEqual(consumer["check_results"], procurement["check_results"])
        self.assertEqual(consumer["claim_results"], procurement["claim_results"])
        self.assertEqual(consumer["status_result"], procurement["status_result"])

    def test_decisions_differ(self):
        consumer = assess(self.SUBJECT, "consumer_v1")
        procurement = assess(self.SUBJECT, "procurement_v1")
        self.assertEqual(consumer["actor_decision"], "allow")
        self.assertEqual(procurement["actor_decision"], "hold")
        self.assertTrue(procurement["narrowed"])
        self.assertFalse(consumer["narrowed"])

    def test_the_narrowing_reason_is_recorded(self):
        procurement = assess(self.SUBJECT, "procurement_v1")
        self.assertIn("seller_not_on_approved_vendor_list", procurement["reason_codes"])


class TestRecallCannotBeSoftened(unittest.TestCase):
    SUBJECT = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"

    def test_blocked_under_every_profile(self):
        for actor_ref in seed.actor_profiles():
            with self.subTest(actor=actor_ref):
                result = assess(self.SUBJECT, actor_ref)
                self.assertEqual(result["actor_decision"], "block")
                self.assertEqual(result["permitted_actions"], ["halt"])
                self.assertEqual(result["selected_action"], "halt")


class TestUnknownProduct(unittest.TestCase):
    def test_unknown_identifier_never_approves(self):
        # The Sprint 1 engine returned `approved` here: verify errored, the
        # claim list came back empty, no branch matched, and the final else
        # approved it.
        for identifier in ("GTIN:00000000000000", "not-a-product", "ramify:demo:supp:invented"):
            with self.subTest(identifier=identifier):
                result = assess(identifier)
                self.assertFalse(result["resolved"])
                self.assertEqual(result["objective_posture"], "escalate")
                self.assertNotIn(result["actor_decision"], ("allow", "allow_with_warning"))

    def test_unresolved_subject_still_produces_a_full_receipt(self):
        receipt = assess("not-a-product")["receipt"]
        self.assertEqual(len(receipt["check_results"]), 7)
        self.assertEqual(receipt["canonical_state"], "observed")
        for check in receipt["check_results"]:
            self.assertEqual(check["outcome"], "incomplete")


class TestActionGate(unittest.TestCase):
    def test_every_selected_action_is_permitted(self):
        for subject_ref in seed.subjects():
            for actor_ref in seed.actor_profiles():
                with self.subTest(subject=subject_ref, actor=actor_ref):
                    result = assess(subject_ref, actor_ref)
                    self.assertIn(result["selected_action"], result["permitted_actions"])

    def test_substitution_is_a_relationship_not_a_posture(self):
        result = assess("ramify:demo:supp:stonefield-zinc-gluc-50-90")
        self.assertIsNotNone(result["substitution"])
        self.assertNotIn("substitution", RESTRICTIVENESS)
        self.assertEqual(result["objective_posture"], "allow_with_warning")
        self.assertEqual(
            result["substitution"]["superseded_by"],
            "ramify:demo:supp:stonefield-zinc-picolinate-50-90",
        )

    def test_the_replacement_product_itself_is_clean(self):
        result = assess("ramify:demo:supp:stonefield-zinc-picolinate-50-90")
        self.assertEqual(result["actor_decision"], "allow")

    def test_no_action_has_a_real_world_effect(self):
        for decision in RESTRICTIVENESS:
            for actor_ref in seed.actor_profiles():
                with self.subTest(decision=decision, actor=actor_ref):
                    self.assertTrue(gate.select(decision, actor_ref, None)["simulated"])


if __name__ == "__main__":
    unittest.main()
