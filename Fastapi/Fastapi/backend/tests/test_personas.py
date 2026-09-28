"""Agent personas, their conditions, and the traffic light.

The client permitted several agents on one condition, stated on 22 July 2026:
they may represent different authorised actors, but they must not debate
whether a product is trustworthy — the trust result stays deterministic and
single-sourced. Most of this file is that constraint, expressed as assertions.
"""

import unittest

from ramify import engine
from ramify.action import gate
from ramify.data import seed
from ramify.policy import actor as actor_policy
from ramify.ratify.precedence import RESTRICTIVENESS

CLEAN = "ramify:demo:supp:apex-mg-glyc-120"            # A$34.95, allow
CHEAP = "ramify:demo:supp:ridgeway-multivit-b2026-02-C"  # A$15.75, escalate
WARNED = "ramify:demo:supp:greenline-ashw-ksm66-90"    # A$49.00, allow_with_warning
RECALLED = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"
OFF_BRAND = "ramify:demo:supp:tidalpoint-omega3-1000-b2025-12-D"  # Tidalpoint, not on allowlist


class TestObjectiveAssessmentIsActorBlind(unittest.TestCase):
    """The single most important property once several agents exist."""

    def test_every_persona_reaches_the_same_objective_posture(self):
        for subject_ref in seed.subjects():
            with self.subTest(subject=subject_ref):
                postures = {
                    engine.assess(subject_ref, actor_ref)["objective_posture"]
                    for actor_ref in seed.actor_profiles()
                }
                self.assertEqual(len(postures), 1, "the assessment saw who was asking")

    def test_the_evidence_behind_it_is_identical_too(self):
        # Not just the same conclusion — the same working.
        receipts = [
            engine.assess(WARNED, actor_ref)["receipt"] for actor_ref in seed.actor_profiles()
        ]
        first = receipts[0]
        for other in receipts[1:]:
            self.assertEqual(first["check_results"], other["check_results"])
            self.assertEqual(first["claim_results"], other["claim_results"])
            self.assertEqual(first["status_result"], other["status_result"])

    def test_quantity_cannot_move_the_objective_posture(self):
        # How many you are buying says nothing about whether the thing is what
        # it claims to be.
        postures = {
            engine.assess(CLEAN, "consumer_v1", None, quantity)["objective_posture"]
            for quantity in (1, 5, 100)
        }
        self.assertEqual(len(postures), 1)


class TestNarrowingInvariant(unittest.TestCase):
    def test_no_persona_ever_widens_any_outcome(self):
        for subject_ref in seed.subjects():
            for actor_ref in seed.actor_profiles():
                for quantity in (1, 12):
                    with self.subTest(subject=subject_ref, actor=actor_ref, qty=quantity):
                        result = engine.assess(subject_ref, actor_ref, None, quantity)
                        self.assertGreaterEqual(
                            RESTRICTIVENESS[result["actor_decision"]],
                            RESTRICTIVENESS[result["objective_posture"]],
                        )

    def test_a_recall_cannot_be_softened_by_any_persona(self):
        for actor_ref in seed.actor_profiles():
            with self.subTest(actor=actor_ref):
                result = engine.assess(RECALLED, actor_ref)
                self.assertEqual(result["actor_decision"], "block")
                self.assertEqual(result["permitted_actions"], ["halt"])

    def test_autonomy_does_not_count_as_widening(self):
        # An autonomous agent buys unattended on a clean result. That changes
        # which action is taken, not how permissive the decision is.
        result = engine.assess(CLEAN, "autonomous_buyer_v1")
        self.assertEqual(result["objective_posture"], "allow")
        self.assertEqual(result["actor_decision"], "allow")
        self.assertTrue(result["unattended"])
        self.assertEqual(result["selected_action"], "purchase_autonomously")


class TestAutonomousBuyer(unittest.TestCase):
    def test_it_buys_unattended_when_the_result_is_clean(self):
        result = engine.assess(CLEAN, "autonomous_buyer_v1")
        self.assertTrue(result["unattended"])
        self.assertFalse(result["requires_human"])

    def test_it_withholds_autonomy_on_a_warned_result(self):
        result = engine.assess(WARNED, "autonomous_buyer_v1")
        self.assertEqual(result["objective_posture"], "allow_with_warning")
        self.assertEqual(result["actor_decision"], "hold")
        self.assertFalse(result["unattended"])
        self.assertIn("autonomy_withheld_on_warned_outcome", result["reason_codes"])

    def test_its_budget_ceiling_stops_a_large_order(self):
        small = engine.assess(CLEAN, "autonomous_buyer_v1", None, 1)
        large = engine.assess(CLEAN, "autonomous_buyer_v1", None, 4)
        self.assertTrue(small["unattended"])
        self.assertEqual(large["actor_decision"], "hold")
        self.assertIn("line_total_exceeds_agent_budget", large["reason_codes"])

    def test_no_persona_purchases_unattended_on_anything_but_a_clean_result(self):
        for subject_ref in seed.subjects():
            for actor_ref in seed.actor_profiles():
                result = engine.assess(subject_ref, actor_ref)
                if result["unattended"]:
                    with self.subTest(subject=subject_ref, actor=actor_ref):
                        self.assertEqual(result["actor_decision"], "allow")


class TestBudgetAndBrandConditions(unittest.TestCase):
    def test_the_budget_agent_holds_over_its_ceiling(self):
        over = engine.assess(CLEAN, "budget_guard_v1")       # A$34.95 > A$30
        under = engine.assess(CHEAP, "budget_guard_v1")      # A$15.75 < A$30
        self.assertEqual(over["actor_decision"], "hold")
        self.assertEqual(under["objective_posture"], under["actor_decision"])

    def test_the_brand_agent_refers_a_brand_off_its_list(self):
        on_list = engine.assess(CLEAN, "brand_loyal_v1")         # Apex Nutrients
        off_list = engine.assess(OFF_BRAND, "brand_loyal_v1")    # Tidalpoint
        self.assertEqual(on_list["actor_decision"], "allow")
        self.assertEqual(off_list["actor_decision"], "hold")
        self.assertIn("brand_outside_agent_arrangement", off_list["reason_codes"])

    def test_a_commercial_narrowing_is_labelled_as_such(self):
        # A brand being off a buyer's list is not a safety finding and the
        # receipt must not let it read as one.
        result = engine.assess(OFF_BRAND, "brand_loyal_v1")
        kinds = {rule["kind"] for rule in result["applied_rules"]}
        self.assertEqual(kinds, {"commercial"})

    def test_a_trust_derived_narrowing_is_labelled_differently(self):
        result = engine.assess(WARNED, "procurement_v1")
        kinds = {rule["kind"] for rule in result["applied_rules"]}
        self.assertIn("trust_derived", kinds)

    def test_conditions_are_reported_whether_met_or_not(self):
        # A persona that shows only its objections reads as an obstacle; one
        # that shows its whole rule set reads as a policy.
        result = engine.assess(CHEAP, "budget_guard_v1")
        self.assertTrue(result["conditions_evaluated"])
        self.assertTrue(all(c["met"] for c in result["conditions_evaluated"]))

    def test_money_stays_in_integer_cents(self):
        receipt = engine.assess(CLEAN, "consumer_v1", None, 3)["receipt"]
        order = receipt["order"]
        self.assertIsInstance(order["unit_price_cents"], int)
        self.assertIsInstance(order["line_total_cents"], int)
        self.assertEqual(order["line_total_cents"], order["unit_price_cents"] * 3)


class TestTrafficLight(unittest.TestCase):
    """Presentation only. Green clean, orange warning/attention, red stop."""

    def test_the_three_lights_and_what_they_mean(self):
        expected = {
            "allow": ("green", "Approved"),
            "allow_with_warning": ("orange", "Approved with warning"),
            "hold": ("orange", "Human review required"),
            "escalate": ("orange", "Human review required"),
            "block": ("red", "Rejected"),
        }
        for posture, (colour, label) in expected.items():
            with self.subTest(posture=posture):
                light = engine.traffic_light(posture)
                self.assertEqual(light["colour"], colour)
                self.assertEqual(light["label"], label)

    def test_only_three_colours_are_ever_used(self):
        colours = {engine.traffic_light(p)["colour"] for p in RESTRICTIVENESS}
        self.assertEqual(colours, {"green", "orange", "red"})

    def test_a_warning_is_amber_without_implying_human_review(self):
        # Client presentation mapping: allow_with_warning is visually amber so
        # it cannot be mistaken for a clean approval. Human involvement is a
        # separate property carried by the decision, not inferred from colour.
        warned = engine.traffic_light("allow_with_warning")
        self.assertEqual(warned["colour"], "orange")
        self.assertTrue(warned["warning"])
        self.assertFalse(engine.traffic_light("allow")["warning"])
        result = engine.assess(WARNED, "consumer_v1", persist_receipt=False)
        self.assertFalse(result["requires_human"])

    def test_no_colour_reaches_the_receipt(self):
        # Client direction of 22 July 2026, item 2. The posture is the decision.
        for subject_ref in seed.subjects():
            with self.subTest(subject=subject_ref):
                receipt = engine.assess(subject_ref)["receipt"]
                serialised = str(receipt)
                self.assertNotIn("traffic_light", receipt)
                self.assertNotIn("Approved", serialised)
                self.assertNotIn("Rejected", serialised)

    def test_human_review_decisions_are_orange_but_warned_allow_may_proceed(self):
        for subject_ref in seed.subjects():
            for actor_ref in seed.actor_profiles():
                result = engine.assess(subject_ref, actor_ref, persist_receipt=False)
                with self.subTest(subject=subject_ref, actor=actor_ref):
                    if result["requires_human"]:
                        self.assertEqual(result["traffic_light"]["colour"], "orange")
                        self.assertIn(result["actor_decision"], ("hold", "escalate"))
                    if result["actor_decision"] == "allow_with_warning":
                        self.assertEqual(result["traffic_light"]["colour"], "orange")

    def test_green_never_means_a_person_is_involved(self):
        for subject_ref in seed.subjects():
            for actor_ref in seed.actor_profiles():
                result = engine.assess(subject_ref, actor_ref)
                if result["traffic_light"]["colour"] == "green":
                    with self.subTest(subject=subject_ref, actor=actor_ref):
                        self.assertFalse(result["requires_human"])


class TestActionGate(unittest.TestCase):
    def test_every_selected_action_is_permitted(self):
        for subject_ref in seed.subjects():
            for actor_ref in seed.actor_profiles():
                with self.subTest(subject=subject_ref, actor=actor_ref):
                    result = engine.assess(subject_ref, actor_ref)
                    self.assertIn(result["selected_action"], result["permitted_actions"])

    def test_nothing_has_a_real_world_effect(self):
        for decision in RESTRICTIVENESS:
            for actor_ref in seed.actor_profiles():
                with self.subTest(decision=decision, actor=actor_ref):
                    self.assertTrue(gate.select(decision, actor_ref, None)["simulated"])

    def test_a_blocked_result_permits_only_halting(self):
        for actor_ref in seed.actor_profiles():
            with self.subTest(actor=actor_ref):
                self.assertEqual(gate.select("block", actor_ref, None)["permitted_actions"], ["halt"])

    def test_an_unknown_persona_is_rejected_rather_than_defaulted(self):
        with self.assertRaises(KeyError):
            actor_policy.apply("allow", "invented_persona", None)


if __name__ == "__main__":
    unittest.main()
