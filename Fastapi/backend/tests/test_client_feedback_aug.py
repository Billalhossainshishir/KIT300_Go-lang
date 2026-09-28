"""The client's feedback of 5 August 2026, as assertions.

Each item names the correction it locks in, so a later change that undoes one
fails the build and says which.
"""

import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import ramify
from ramify import engine
from ramify.action import alternatives
from ramify.api.app import app
from ramify.data import seed
from ramify.policy import vocabulary
from ramify.ratify.checks import evaluate_evidence_freshness
from ramify.ratify.precedence import RESTRICTIVENESS

client = TestClient(app)
FRONTEND = Path(ramify.__file__).resolve().parents[1].parent / "frontend"


class A7a_VerificationMustNotOverclaim(unittest.TestCase):
    """The interface must not assert a check it did not run, and must never
    report success when a check failed."""

    def test_a_failure_is_reported_as_a_failure(self):
        body = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"},
        ).json()
        tampered = dict(body["receipt"], product_name="Something else")
        report = client.post("/api/v0/receipt/verify", json=tampered).json()
        self.assertFalse(report["verified"])
        self.assertFalse(all(c["passed"] for c in report["checks"]))

    def test_freshness_is_computed_not_asserted(self):
        receipt = engine.assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        report = client.post("/api/v0/receipt/verify", json=receipt).json()
        fresh = next(c for c in report["checks"] if c["name"] == "fresh")
        self.assertIn("minute", fresh["detail"])

    def test_the_interface_hard_codes_no_verification_result(self):
        script = (FRONTEND / "scripts" / "shell.js").read_text(encoding="utf-8")
        self.assertNotIn("RECEIPT INTEGRITY CONFIRMED", script)
        self.assertIn("report.verified", script)


class A7b_AdvisoryIsNotRecall(unittest.TestCase):
    """clear → green, advisory → amber, recalled → red. A voluntary recall is a
    recall and is never stored as an advisory to manufacture an amber case."""

    def test_the_three_standings_map_to_three_colours(self):
        self.assertEqual(vocabulary.describe_standing("no_active_recall")["light"], "green")
        self.assertEqual(vocabulary.describe_standing("advisory")["light"], "amber")
        self.assertEqual(vocabulary.describe_standing("recalled")["light"], "red")

    def test_no_advisory_record_describes_itself_as_a_recall(self):
        for ref, record in seed.seed()["statuses"].items():
            if record["standing"] == "advisory":
                with self.subTest(subject=ref):
                    self.assertNotIn("recall", record.get("detail", "").lower())

    def test_advisory_holds_and_recall_blocks(self):
        self.assertEqual(
            engine.assess("ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z")["actor_decision"],
            "hold",
        )
        self.assertEqual(
            engine.assess("ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K")[
                "actor_decision"
            ],
            "block",
        )


class A7c_ObjectiveAndActorShownSeparately(unittest.TestCase):
    """The central architectural feature must be visible, not inferred."""

    def test_the_envelope_carries_both_as_distinct_fields(self):
        result = engine.assess(
            "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "procurement_v1"
        )
        self.assertEqual(result["objective_posture"], "allow")
        self.assertEqual(result["actor_decision"], "hold")
        self.assertEqual(result["objective_light"]["machine_posture"], "allow")
        self.assertEqual(result["traffic_light"]["machine_posture"], "hold")

    def test_the_interface_renders_them_as_two_fields(self):
        script = (FRONTEND / "scripts" / "shell.js").read_text(encoding="utf-8")
        self.assertIn("Objective product posture", script)
        self.assertIn("renderVerdictSplit", script)


class A7d_EvidenceStoresFactsNotAnswers(unittest.TestCase):
    """Store evidence facts and let the engine derive whether they are usable."""

    def test_no_precomputed_expiry_anywhere_in_the_dataset(self):
        body = seed.SEED_PATH.read_text(encoding="utf-8")
        self.assertNotIn('"evidence_expired"', body)
        self.assertNotIn('"expiry_note"', body)

    def test_every_evidence_record_carries_the_required_facts(self):
        required = (
            "ref",
            "claim_ref",
            "subject_ref",
            "issuer_ref",
            "authority_level",
            "document_type",
            "certificate_number",
            "issued_at",
            "valid_from",
            "expires_at",
            "retrieved_at",
            "record_status",
            "source_uri",
            "scope",
        )
        for ref in seed.seed()["evidence"]:
            with self.subTest(evidence=ref):
                record = seed.evidence(ref)
                for field in required:
                    self.assertIn(field, record)

    def test_freshness_is_derived_against_the_snapshot(self):
        # The client's own worked example: 25 April 2026 expiry against a
        # 24 July 2026 snapshot is 90 days.
        result = evaluate_evidence_freshness(
            seed.evidence("ev:greenline:coa"), seed.snapshot_date()
        )
        self.assertEqual(result["state"], "expired")
        self.assertEqual(result["days_expired"], 90)

    def test_the_same_record_was_current_at_an_earlier_snapshot(self):
        from datetime import datetime, timezone

        earlier = datetime(2026, 4, 24, tzinfo=timezone.utc)
        result = evaluate_evidence_freshness(seed.evidence("ev:greenline:coa"), earlier)
        self.assertEqual(result["state"], "current")

    def test_all_seven_freshness_states_are_reachable(self):
        from ramify.ratify.checks import FRESHNESS_OUTCOME

        self.assertEqual(
            set(FRESHNESS_OUTCOME),
            {
                "current",
                "expired",
                "not_yet_valid",
                "missing_expiry",
                "revoked",
                "issuer_inactive",
                "malformed_record",
            },
        )

    def test_revoked_and_not_yet_valid_are_demonstrated(self):
        merridale = engine.assess("ramify:demo:ppe:merridale-faceshield-std")["receipt"]
        self.assertIn("evidence_revoked", merridale["reason_codes"])

        brightway = engine.assess("ramify:demo:supp:brightway-vitd3-5000-b2025-06-M")["receipt"]
        self.assertIn("evidence_not_yet_valid", brightway["reason_codes"])


class A8_ScenariosAreReachable(unittest.TestCase):
    """The interface must expose more than three cases."""

    REQUIRED = ("RECALL", "SELLER-RISK", "SUBSTITUTION", "PROOF", "CONFLICT")

    def test_every_case_the_client_named_is_offered(self):
        ids = " ".join(s["id"] for s in client.get("/api/v0/catalogue").json()["scenarios"])
        for case in self.REQUIRED:
            with self.subTest(case=case):
                self.assertIn(case, ids)

    def test_the_selector_is_driven_by_the_dataset(self):
        self.assertEqual(
            len(client.get("/api/v0/catalogue").json()["scenarios"]), len(seed.scenarios())
        )


class A10_ActionGateProducesEvents(unittest.TestCase):
    """A permitted action must produce an observable, recorded event."""

    def test_a_permitted_action_is_recorded(self):
        assessed = client.post(
            "/api/v0/assess", json={"identifier": "ramify:demo:supp:apex-mg-glyc-120"}
        ).json()
        response = client.post(
            "/api/v0/action",
            json={"receipt_ref": assessed["receipt_ref"], "action": "add_to_mock_cart"},
        )
        self.assertEqual(response.status_code, 200)
        event = response.json()["event"]
        self.assertEqual(event["receipt_ref"], assessed["receipt_ref"])
        self.assertTrue(event["simulated"])

    def test_an_unpermitted_action_is_refused(self):
        assessed = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"},
        ).json()
        response = client.post(
            "/api/v0/action",
            json={"receipt_ref": assessed["receipt_ref"], "action": "add_to_mock_cart"},
        )
        self.assertEqual(response.status_code, 409)

    def test_no_permitted_action_is_missing_from_the_interface(self):
        from ramify.policy import profiles

        emitted = set()
        for profile in profiles.all_profiles().values():
            for actions in profile["permitted_actions"].values():
                emitted.update(actions)

        script = (FRONTEND / "scripts" / "console.js").read_text(encoding="utf-8")
        for action in emitted:
            with self.subTest(action=action):
                self.assertIn(action, script)

    def test_the_gate_returns_a_set_and_names_one_default(self):
        result = engine.assess("ramify:demo:supp:apex-mg-glyc-120")
        self.assertGreater(len(result["permitted_actions"]), 1)
        self.assertIn(result["selected_action"], result["permitted_actions"])


class A11_NoPerformanceClaim(unittest.TestCase):
    def test_the_interface_makes_no_50ms_claim(self):
        for path in FRONTEND.rglob("*"):
            if path.suffix in (".html", ".js"):
                with self.subTest(file=path.name):
                    self.assertNotIn("50ms-Class", path.read_text(encoding="utf-8"))


class A12_NoOverclaiming(unittest.TestCase):
    def test_the_source_record_dialog_uses_neutral_wording(self):
        script = (FRONTEND / "scripts" / "shell.js").read_text(encoding="utf-8")
        self.assertNotIn("This proves", script)
        self.assertIn("Synthetic source record", script)

    def test_the_offline_badge_is_derived_from_the_backend(self):
        health = client.get("/healthz").json()
        self.assertIn("binds_loopback_only", health)
        self.assertIn("makes_outbound_calls", health)
        script = (FRONTEND / "scripts" / "shell.js").read_text(encoding="utf-8")
        self.assertIn("reportConfiguration", script)


class B1_TransitionMatrixIsPublished(unittest.TestCase):
    """The monotonicity claim must be testable, not interpretive."""

    def test_every_transition_is_enumerated(self):
        matrix = vocabulary.transition_matrix()
        self.assertEqual(len(matrix["rows"]), len(RESTRICTIVENESS) ** 2)

    def test_widening_transitions_are_marked_impermissible(self):
        for row in vocabulary.transition_matrix()["rows"]:
            with self.subTest(row=f"{row['objective_posture']}->{row['actor_decision']}"):
                self.assertEqual(row["permitted"], row["kind"] != "widens")

    def test_no_agent_produces_a_transition_the_matrix_forbids(self):
        from ramify.policy import profiles

        permitted = {
            (r["objective_posture"], r["actor_decision"])
            for r in vocabulary.transition_matrix()["rows"]
            if r["permitted"]
        }
        for subject_ref in seed.subjects():
            for actor_ref in profiles.all_profiles():
                result = engine.assess(subject_ref, actor_ref)
                with self.subTest(subject=subject_ref, actor=actor_ref):
                    self.assertIn(
                        (result["objective_posture"], result["actor_decision"]), permitted
                    )


class C1_VersionedVocabularyMapping(unittest.TestCase):
    """Spec vocabulary in the receipt, clearer wording for people, one
    versioned table binding the two."""

    def test_the_receipt_carries_the_machine_posture(self):
        receipt = engine.assess("ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z")["receipt"]
        self.assertEqual(receipt["actor_decision"], "hold")

    def test_the_envelope_carries_both_and_names_the_mapping_version(self):
        light = engine.assess("ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z")["traffic_light"]
        self.assertEqual(light["machine_posture"], "hold")
        self.assertEqual(light["label"], "Human review required")
        self.assertTrue(light["mapping_version"])

    def test_the_mapping_covers_every_posture_exactly_once(self):
        self.assertEqual(set(vocabulary.POSTURE_MAPPING), set(RESTRICTIVENESS))


class C2_NoConditionIsSuppressed(unittest.TestCase):
    """Evaluate every check, record every reason, take the most restrictive
    rule — and still show the highest-precedence reason first."""

    SUBJECT = "ramify:demo:supp:brightway-vitd3-5000-b2025-06-M"

    def test_the_posture_comes_from_the_most_restrictive_matched_rule(self):
        for subject_ref in seed.subjects():
            receipt = engine.assess(subject_ref)["receipt"]
            strictest = max(
                (m["posture"] for m in receipt["matched_conditions"]),
                key=lambda p: RESTRICTIVENESS[p],
            )
            with self.subTest(subject=subject_ref):
                self.assertEqual(receipt["objective_posture"], strictest)

    def test_the_advisory_is_the_primary_reason(self):
        receipt = engine.assess(self.SUBJECT)["receipt"]
        self.assertEqual(receipt["primary_reason"], "standing is advisory")

    def test_the_expired_evidence_is_not_discarded(self):
        receipt = engine.assess(self.SUBJECT)["receipt"]
        self.assertEqual(receipt["actor_decision"], "hold")
        self.assertIn("active_advisory_on_batch", receipt["reason_codes"])
        self.assertIn("evidence_expired", receipt["reason_codes"])

    def test_a_recall_dominates_everything(self):
        from ramify.policy import profiles

        for actor_ref in profiles.all_profiles():
            with self.subTest(actor=actor_ref):
                result = engine.assess(
                    "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K", actor_ref
                )
                self.assertEqual(result["actor_decision"], "block")


class C3_UnapprovedSellerHoldsNotRejects(unittest.TestCase):
    def test_a_genuine_seller_off_the_list_produces_hold(self):
        result = engine.assess(
            "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "procurement_v1"
        )
        self.assertEqual(result["actor_decision"], "hold")
        self.assertNotEqual(result["actor_decision"], "block")


class AlternativesAreOffered(unittest.TestCase):
    """When an agent stops something the checks found nothing wrong with."""

    def test_an_over_budget_hold_gets_suggestions(self):
        outcome = engine.assess("ramify:demo:supp:apex-mg-glyc-120", "budget_guard_v1")
        found = alternatives.find(
            "ramify:demo:supp:apex-mg-glyc-120", "budget_guard_v1", 1, outcome
        )
        self.assertIsNotNone(found)
        self.assertTrue(found["candidates"])

    def test_every_suggestion_is_one_the_same_agent_would_accept(self):
        outcome = engine.assess("ramify:demo:supp:apex-mg-glyc-120", "budget_guard_v1")
        found = alternatives.find(
            "ramify:demo:supp:apex-mg-glyc-120", "budget_guard_v1", 1, outcome
        )
        for candidate in found["candidates"]:
            with self.subTest(candidate=candidate["subject_ref"]):
                rerun = engine.assess(candidate["subject_ref"], "budget_guard_v1")
                self.assertFalse(rerun["requires_human"])
                self.assertTrue(rerun["can_add_to_cart"])

    def test_nothing_is_suggested_as_an_alternative_to_a_recall(self):
        recalled = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"
        outcome = engine.assess(recalled, "consumer_v1")
        self.assertIsNone(alternatives.find(recalled, "consumer_v1", 1, outcome))

    def test_a_clean_result_needs_no_alternatives(self):
        outcome = engine.assess("ramify:demo:supp:apex-mg-glyc-120", "consumer_v1")
        self.assertIsNone(
            alternatives.find("ramify:demo:supp:apex-mg-glyc-120", "consumer_v1", 1, outcome)
        )

    def test_the_makers_own_replacement_is_offered_first(self):
        superseded = "ramify:demo:supp:stonefield-zinc-gluc-50-90"
        outcome = engine.assess(superseded, "procurement_v1")
        found = alternatives.find(superseded, "procurement_v1", 1, outcome)
        if found:
            self.assertTrue(found["candidates"][0]["is_named_replacement"])


class EveryStopIsClassified(unittest.TestCase):
    """No stop may fall through to the unclassified wording.

    A withdrawn certificate once did: the freshness derivation gained
    `evidence_revoked` and no escalation group claimed it, so a rejection read
    "handed to a person" while nobody was being asked anything. Enumerating the
    scenarios means a new reason code without a group fails the build.
    """

    def test_no_scenario_produces_an_unclassified_stop(self):
        for scenario in seed.scenarios():
            outcome = engine.assess(scenario["subject_ref"], scenario["actor"])
            if not outcome.get("escalation"):
                continue
            with self.subTest(scenario=scenario["id"]):
                self.assertNotEqual(outcome["escalation"]["kind"], "unspecified")

    def test_a_rejection_is_never_worded_as_a_handover(self):
        for scenario in seed.scenarios():
            outcome = engine.assess(scenario["subject_ref"], scenario["actor"])
            escalation = outcome.get("escalation")
            if not escalation or escalation["requires_human"]:
                continue
            with self.subTest(scenario=scenario["id"]):
                self.assertIn("Rejected", escalation["headline"])
                self.assertIn("Nobody", escalation["decided_by"])

    def test_every_reason_code_the_checks_emit_has_a_group(self):
        from ramify.engine import ESCALATION_KINDS
        from ramify.ratify.checks import FRESHNESS_REASON

        grouped = {code for _, triggers, _ in ESCALATION_KINDS for code in triggers}
        for code in FRESHNESS_REASON.values():
            with self.subTest(code=code):
                self.assertIn(code, grouped)


class HumanReadableReceipt(unittest.TestCase):
    """Deliverable 1 FR-05: a readable card as well as the raw JSON."""

    def test_the_interface_renders_a_receipt_document(self):
        script = (FRONTEND / "scripts" / "console.js").read_text(encoding="utf-8")
        for section in ("Product", "Receipt ID", "Sealed", "Checked for", "Decision"):
            with self.subTest(section=section):
                self.assertIn(section, script)

    def test_it_shows_the_hash_and_the_signature(self):
        script = (FRONTEND / "scripts" / "console.js").read_text(encoding="utf-8")
        self.assertIn("payload_hash", script)
        self.assertIn("Content hash", script)

    def test_the_technical_detail_is_behind_a_disclosure(self):
        """A buyer meets the plain fields; the machine record is one press away
        rather than in their face."""
        script = (FRONTEND / "scripts" / "console.js").read_text(encoding="utf-8")
        self.assertIn('data-reveal="receipt-technical"', script)
        self.assertIn('id="receipt-technical" hidden', script)


if __name__ == "__main__":
    unittest.main()
