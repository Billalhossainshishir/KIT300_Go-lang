"""David Male's feedback of 1 October 2026 and the 2 October review, as tests.

Each class names the item it locks in. Every case runs against a throwaway
``RAMIFY_DATA_DIR``; dataset changes are made to an in-memory copy, so the
signed artefacts and signatures on disk are never touched.
"""

import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ramify import engine
from ramify.api.app import app
from ramify.data import seed

client = TestClient(app)

APEX = "ramify:demo:supp:apex-mg-glyc-120"
GREENLINE = "ramify:demo:supp:greenline-ashw-ksm66-90"
BRIGHTWAY_M = "ramify:demo:supp:brightway-vitd3-5000-b2025-06-M"
MERRIDALE = "ramify:demo:ppe:merridale-faceshield-std"
HARBORLINE = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"


class TempStoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"RAMIFY_DATA_DIR": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def mutated(self, change):
        data = copy.deepcopy(seed.seed())
        change(data)
        return patch.object(seed, "seed", return_value=data)

    def without_signature(self, *evidence_refs):
        signatures = copy.deepcopy(seed.evidence_signatures())
        for ref in evidence_refs:
            signatures.pop(ref, None)
        return patch.object(seed, "evidence_signatures", return_value=signatures)

    def posture(self, subject_ref):
        return engine.assess(subject_ref, context="purchase", persist_receipt=False)["objective_posture"]

    def assess(self, subject_ref, actor_ref="consumer_v1"):
        response = client.post("/api/v0/assess", json={
            "identifier": subject_ref, "actor_ref": actor_ref, "quantity": 1, "context": "purchase",
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["receipt"]


class TestItem2IntegrityStopsSurviveCombination(TempStoreCase):
    """Missing integrity proof keeps its stop when an ordinary warning is also
    present."""

    def test_expired_on_its_own_is_a_warning(self):
        self.assertEqual(self.posture(GREENLINE), "allow_with_warning")

    def test_expired_and_missing_signature_escalates(self):
        with self.without_signature("ev:greenline:coa"):
            result = engine.assess(GREENLINE, context="purchase", persist_receipt=False)
        self.assertEqual(result["objective_posture"], "escalate")
        self.assertIn("evidence_integrity_metadata_missing", result["reason_codes"])
        self.assertIn("evidence_expired", result["reason_codes"])

    def test_not_yet_valid_and_missing_signature_escalates(self):
        with self.without_signature("ev:brightway-m:gmp"):
            self.assertEqual(self.posture(BRIGHTWAY_M), "escalate")

    def test_missing_signature_on_a_clean_product_escalates(self):
        with self.without_signature("ev:apex:coa"):
            self.assertEqual(self.posture(APEX), "escalate")

    def test_revoked_and_missing_signature_still_blocks(self):
        with self.without_signature("ev:merridale:conformity"):
            self.assertEqual(self.posture(MERRIDALE), "block")


class CartCase(TempStoreCase):
    def setUp(self):
        super().setUp()
        from ramify.action import cart
        self.cart = cart
        cart.clear()

    def stage(self, subject_ref=APEX, actor_ref="consumer_v1"):
        receipt = self.assess(subject_ref, actor_ref)
        self.cart.add(receipt["receipt_id"])
        return receipt


class TestItem3StaleAuthorityIsRefusedAtCheckout(CartCase):
    """A recall or other change to the trusted local data after a line was
    staged must stop checkout."""

    def test_recall_after_staging_refuses_checkout(self):
        self.stage()
        with self.mutated(lambda d: d["statuses"][APEX].update(standing="recalled", reason="test")):
            with self.assertRaises(self.cart.CartRefused) as caught:
                self.cart.checkout()
        self.assertIn("changed since this decision was sealed", str(caught.exception))
        self.assertEqual(self.cart.contents()["orders"], [])

    def test_price_change_after_staging_refuses_checkout(self):
        self.stage()

        def reprice(data):
            data["listings"]["prices_cents"][APEX] += 100

        with self.mutated(reprice):
            with self.assertRaises(self.cart.CartRefused):
                self.cart.checkout()

    def test_change_to_an_unrelated_product_does_not_void_the_basket(self):
        self.stage()
        with self.mutated(lambda d: d["statuses"][HARBORLINE].update(reason="updated wording")):
            order = self.cart.checkout()
        self.assertEqual(len(order["lines"]), 1)

    def test_unchanged_data_checks_out(self):
        self.stage()
        self.assertEqual(len(self.cart.checkout()["lines"]), 1)

    def test_recall_also_blocks_staging_a_fresh_receipt(self):
        receipt = self.assess(APEX)
        with self.mutated(lambda d: d["statuses"][APEX].update(standing="recalled", reason="test")):
            with self.assertRaises(self.cart.CartRefused):
                self.cart.add(receipt["receipt_id"])


class TestItem4AutonomyStatementComesFromTheReceipt(CartCase):
    def summary(self, order):
        return order["customer_summary"]["how_the_order_was_authorised"]

    def test_an_edited_unattended_flag_is_refused(self):
        self.stage()
        data = self.cart._read()
        data["lines"][0]["unattended"] = True
        self.cart._write(data)
        with self.assertRaises(self.cart.CartRefused) as caught:
            self.cart.checkout()
        self.assertIn("autonomy", str(caught.exception))

    def test_an_assisted_line_is_not_described_as_autonomous(self):
        self.stage()
        self.assertIn("0 line(s) were permitted for autonomous purchase", self.summary(self.cart.checkout()))

    def test_a_genuinely_autonomous_line_is_described_as_such(self):
        receipt = self.stage(actor_ref="autonomous_buyer_v1")
        self.assertEqual(receipt["selected_action"], "purchase_autonomously")
        self.assertIn("1 line(s) were permitted for autonomous purchase", self.summary(self.cart.checkout()))


class TestItem5AuthorityReportingIsAccurate(CartCase):
    """Record integrity, the time window, the permitted action and unused
    authority are reported separately, and only all four make it current."""

    HELD = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"

    def verify(self, receipt):
        return client.post("/api/v0/receipt/verify", json=receipt).json()

    def test_a_fresh_clean_receipt_is_current(self):
        report = self.verify(self.assess(APEX))
        self.assertTrue(report["purchase_authority_valid"])
        self.assertEqual(report["authority_status"], "current")

    def test_a_fresh_blocked_receipt_is_intact_but_not_authority(self):
        report = self.verify(self.assess(HARBORLINE))
        self.assertTrue(report["integrity_verified"])
        self.assertTrue(report["time_window_valid"])
        self.assertFalse(report["permits_purchase"])
        self.assertFalse(report["purchase_authority_valid"])
        self.assertEqual(report["authority_status"], "no_purchase_permitted")

    def test_a_consumed_receipt_is_history_not_authority(self):
        receipt = self.stage()
        self.cart.checkout()
        report = self.verify(receipt)
        self.assertTrue(report["integrity_verified"])
        self.assertFalse(report["transaction_authority_unused"])
        self.assertFalse(report["purchase_authority_valid"])
        self.assertEqual(report["authority_status"], "already_used")

    def test_an_answered_review_is_not_current_authority(self):
        receipt = self.assess(self.HELD)
        answered = client.post("/api/v0/receipt/review", json={
            "receipt_id": receipt["receipt_id"], "outcome": "confirmed",
        })
        self.assertEqual(answered.status_code, 200, answered.text)
        self.assertFalse(self.verify(receipt)["purchase_authority_valid"])

    def test_a_held_receipt_can_still_be_reviewed(self):
        receipt = self.assess(self.HELD)
        self.assertEqual(self.verify(receipt)["authority_status"], "no_purchase_permitted")
        response = client.post("/api/v0/receipt/review", json={
            "receipt_id": receipt["receipt_id"], "outcome": "overridden",
        })
        self.assertEqual(response.status_code, 200, response.text)

    def test_the_offline_verifier_does_not_guess_about_use(self):
        from ramify.crypto.sign import verify_receipt
        report = verify_receipt(self.assess(APEX))
        self.assertIsNone(report["transaction_authority_unused"])
        self.assertEqual(report["authority_status"], "current_unchecked_use")


class TestItem6ModelOutputIsValidated(unittest.TestCase):
    """Malformed model output falls back cleanly instead of raising or being
    read as confident."""

    CATALOGUE = [{"subject_ref": APEX, "name": "Apex"}]

    def interpret(self, raw):
        from types import SimpleNamespace

        from ramify.agent.pydanticai_adapter import PydanticAIAdapter

        adapter = PydanticAIAdapter()
        adapter._agent = SimpleNamespace(run_sync=lambda prompt: SimpleNamespace(output=raw))
        return adapter.interpret("magnesium", self.CATALOGUE)

    def test_an_array_falls_back(self):
        reading = self.interpret("[]")
        self.assertIsNone(reading.identifier)
        self.assertEqual(reading.confidence, 0.0)

    def test_a_list_identifier_falls_back(self):
        self.assertIsNone(self.interpret('{"identifier": ["%s"], "confidence": 0.9}' % APEX).identifier)

    def test_nan_confidence_is_not_full_confidence(self):
        for raw_value in ('"NaN"', '"nan"', '"Infinity"', '"-Infinity"', "true", '"high"', "null"):
            with self.subTest(confidence=raw_value):
                reading = self.interpret('{"identifier": "%s", "confidence": %s}' % (APEX, raw_value))
                self.assertEqual(reading.identifier, APEX)
                self.assertEqual(reading.confidence, 0.0)

    def test_a_valid_confidence_is_kept_and_clamped(self):
        self.assertEqual(self.interpret('{"identifier": "%s", "confidence": 0.8}' % APEX).confidence, 0.8)
        self.assertEqual(self.interpret('{"identifier": "%s", "confidence": 7}' % APEX).confidence, 1.0)

    def test_the_shared_rule_covers_both_adapters(self):
        from ramify.agent import langgraph_adapter, pydanticai_adapter
        from ramify.agent.protocol import bounded_confidence

        self.assertIs(langgraph_adapter.bounded_confidence, bounded_confidence)
        self.assertIs(pydanticai_adapter.bounded_confidence, bounded_confidence)


class TestReviewR01OneProfilePerAssessment(TempStoreCase):
    """An edit to the agent between policy and action selection must not mix
    two versions of the agent in one receipt."""

    def test_a_profile_swap_mid_assessment_cannot_grant_unattended_buying(self):
        from ramify.policy import profiles

        original = copy.deepcopy(profiles.profile("consumer_v1"))
        edited = copy.deepcopy(profiles.profile("autonomous_buyer_v1"))
        edited["label"] = original["label"]
        calls = []

        def swapping(ref):
            calls.append(ref)
            return copy.deepcopy(original if len(calls) == 1 else edited)

        with patch.object(profiles, "profile", side_effect=swapping):
            receipt = engine.assess(APEX, "consumer_v1", context="purchase", persist_receipt=False)["receipt"]
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(receipt["selected_action"], "purchase_autonomously")

    def test_the_receipt_seals_the_profile_it_evaluated(self):
        from ramify.policy import profiles

        receipt = engine.assess(APEX, "consumer_v1", context="purchase", persist_receipt=False)["receipt"]
        self.assertEqual(receipt["actor_profile_digest"], seed._content_digest(profiles.profile("consumer_v1")))


class TestClaimChecksCombineEveryFinding(TempStoreCase):
    """A missing required claim must not hide another claim's broken binding."""

    def claims_check(self, change):
        from ramify.ratify import checks

        with self.mutated(change):
            return checks.check_claims_and_category(seed.subject(APEX))

    def test_missing_claim_and_broken_binding_together_hard_stop(self):
        def change(data):
            subject = data["subjects"][APEX]
            required = data["categories"][subject["category"]]["required_claim_types"]
            kept = [c for c in subject["claims"] if c["type"] != required[0]]
            self.assertLess(len(kept), len(subject["claims"]))
            kept[0]["value"] = kept[0]["value"] + " (edited)"
            subject["claims"] = kept

        result = self.claims_check(change)
        self.assertEqual((result.outcome, result.severity), ("fail", "hard_stop"))
        self.assertIn("required_claim_missing", result.reason_codes)
        self.assertIn("claim_evidence_binding_invalid", result.reason_codes)

    def test_missing_claim_alone_is_incomplete(self):
        def change(data):
            subject = data["subjects"][APEX]
            required = data["categories"][subject["category"]]["required_claim_types"]
            subject["claims"] = [c for c in subject["claims"] if c["type"] != required[0]]

        result = self.claims_check(change)
        self.assertEqual(result.outcome, "incomplete")
        self.assertEqual(result.reason_codes, ["required_claim_missing"])

    def test_genuine_claims_pass(self):
        self.assertEqual(self.claims_check(lambda data: None).outcome, "pass")


class TestProcurementAlternativesAreOffered(TempStoreCase):
    NORTHBEAM = "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A"

    def alternatives_for(self, actor_ref):
        from ramify.action import alternatives

        outcome = engine.assess(self.NORTHBEAM, actor_ref, None, 1, context="purchase", persist_receipt=False)
        return alternatives.find(self.NORTHBEAM, actor_ref, 1, outcome)

    def test_a_commercial_procurement_hold_gets_requisitionable_alternatives(self):
        found = self.alternatives_for("procurement_v1")
        self.assertIsNotNone(found)
        refs = {c["subject_ref"]: c["transaction_path"] for c in found["candidates"]}
        self.assertEqual(refs.get(APEX), "requisition")


class TestReviewPageKeepsTheWarning(unittest.TestCase):
    """allow_with_warning is not filed as a purely commercial stop."""

    def setUp(self):
        from pathlib import Path

        import ramify

        root = Path(ramify.__file__).resolve().parents[2]
        self.js = (root / "frontend" / "scripts" / "review.js").read_text(encoding="utf-8")

    def test_warned_outcomes_have_their_own_kind(self):
        self.assertIn('if (r.objective_posture === "allow_with_warning") return "warning";', self.js)
        self.assertIn('if (r.objective_posture === "allow") return "commercial";', self.js)
        self.assertNotIn('["allow", "allow_with_warning"].includes(r.objective_posture)', self.js)

    def test_the_warning_kind_has_its_own_explanation_and_advice(self):
        self.assertIn("  warning: (r) =>", self.js)
        self.assertIn("  warning:\n", self.js)


class TestReleaseCheckFindsKeysAnywhere(unittest.TestCase):
    """David's fixture: runtime_data/signer_key.json passed the release check."""

    def test_a_signer_key_under_runtime_data_fails_the_release(self):
        import importlib.util
        import io
        from contextlib import redirect_stdout
        from pathlib import Path

        import ramify

        script = Path(ramify.__file__).resolve().parents[2] / "scripts" / "release_check.py"
        spec = importlib.util.spec_from_file_location("release_check_under_test", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "runtime_data").mkdir()
            (Path(root) / "runtime_data" / "signer_key.json").write_text('{"seed": "x"}', encoding="utf-8")
            with patch.object(module, "ROOT", Path(root)), \
                    patch.object(module, "_known_public_keys", return_value=set()), \
                    redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    module.check_no_private_keys()
        self.assertEqual(caught.exception.code, 1)


class TestReviewR07VersionedAssetsCache(unittest.TestCase):
    def cache(self, path):
        return client.get(path).headers["cache-control"]

    def test_a_versioned_stylesheet_and_script_are_cacheable(self):
        self.assertIn("immutable", self.cache("/style.css?v=build-1"))
        self.assertIn("immutable", self.cache("/shell.js?v=build-1"))

    def test_pages_decisions_and_unversioned_assets_are_never_cached(self):
        for path in ("/style.css", "/shop?v=1", "/api/v0/catalogue?v=1", "/missing.css?v=1"):
            with self.subTest(path=path):
                self.assertIn("no-store", self.cache(path))


class TestEveryApplicablePolicyReasonIsRetained(unittest.TestCase):
    """Two rules reaching the same restrictive posture are both recorded."""

    def test_two_rules_to_the_same_posture_both_appear(self):
        from ramify.policy import actor as actor_policy
        from ramify.policy import profiles

        profile = copy.deepcopy(profiles.profile("consumer_v1"))
        profile.update(budget_limit_cents=1, brand_allowlist=["Some Other Brand"])
        profile["narrowing_rules"] = [
            {"id": "over_budget", "narrow_to": "hold", "reason_code": "actor_budget_exceeded"},
            {"id": "brand_not_on_allowlist", "narrow_to": "hold", "reason_code": "actor_brand_not_allowed"},
        ]
        decision = actor_policy.apply(
            "allow", "consumer_v1", seed.subject(APEX),
            {"quantity": 1, "unit_price_cents": 3495, "line_total_cents": 3495},
            profile=profile,
        )
        self.assertEqual(decision.decision, "hold")
        self.assertEqual(
            [rule["rule_id"] for rule in decision.applied_rules], ["over_budget", "brand_not_on_allowlist"]
        )
        self.assertEqual(decision.reason_codes, ["actor_budget_exceeded", "actor_brand_not_allowed"])

    def test_a_weaker_rule_is_recorded_but_does_not_decide(self):
        from ramify.policy import actor as actor_policy
        from ramify.policy import profiles

        profile = copy.deepcopy(profiles.profile("consumer_v1"))
        profile.update(budget_limit_cents=1, brand_allowlist=["Some Other Brand"])
        profile["narrowing_rules"] = [
            {"id": "over_budget", "narrow_to": "hold", "reason_code": "actor_budget_exceeded"},
            {"id": "brand_not_on_allowlist", "narrow_to": "escalate", "reason_code": "actor_brand_not_allowed"},
        ]
        decision = actor_policy.apply(
            "allow", "consumer_v1", seed.subject(APEX),
            {"quantity": 1, "unit_price_cents": 3495, "line_total_cents": 3495},
            profile=profile,
        )
        self.assertEqual(decision.decision, "escalate")
        determines = {rule["rule_id"]: rule["determines_outcome"] for rule in decision.applied_rules}
        self.assertEqual(determines, {"over_budget": False, "brand_not_on_allowlist": True})


if __name__ == "__main__":
    unittest.main()
