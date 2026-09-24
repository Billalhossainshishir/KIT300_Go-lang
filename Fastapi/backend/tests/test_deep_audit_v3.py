"""Deep-audit regressions for transaction, evidence and adapter hardening."""

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from ramify import engine
from ramify.action import alternatives, cart
from ramify.agent.pydanticai_adapter import PydanticAIAdapter
from ramify.api.app import app
from ramify.crypto.canonical import rfc3339_nano
from ramify.crypto.sign import seal, verify_receipt
from ramify.data import seed
from ramify.policy import actor as actor_policy
from ramify.ratify import checks
from ramify.receipt import store
from ramify.resolve import primitives

client = TestClient(app)
APEX = "ramify:demo:supp:apex-mg-glyc-120"
NORTHBEAM = "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A"


class TempStoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"RAMIFY_DATA_DIR": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()


class TestResolveAndInputBoundary(unittest.TestCase):
    def test_identify_is_deterministic_and_has_no_confidence(self):
        subject = seed.subject(APEX)
        gtin = subject["identifiers"]["gtin"]
        result = primitives.identify(f"gtin:{gtin}")
        self.assertTrue(result["resolved"])
        self.assertEqual(result["subject_ref"], APEX)
        self.assertEqual(result["match_method"], "exact_gtin")
        self.assertNotIn("confidence", result)

    def test_explicit_identifier_namespace_is_not_cross_matched(self):
        subject = seed.subject(APEX)
        sku = subject["identifiers"]["sku"]
        result = primitives.identify(f"gtin:{sku}")
        self.assertFalse(result["resolved"])
        self.assertEqual(result["match_method"], "no_exact_match")

    def test_engine_rejects_invalid_quantities_even_without_http_boundary(self):
        for bad in (0, -1, 1001, True, 1.5):
            with self.subTest(quantity=bad):
                with self.assertRaises(ValueError):
                    engine.assess(APEX, quantity=bad, persist_receipt=False)


class TestPolicySafety(unittest.TestCase):
    def test_budget_with_unknown_price_fails_to_hold(self):
        subject = seed.subject(APEX)
        profile = {
            "ref": "budget-test",
            "label": "Budget test",
            "budget_limit_cents": 5000,
            "brand_allowlist": [],
            "approved_vendors": [],
            "warned_outcome_requires_review": False,
            "autonomy_level": "none",
            "purchase_style": "cart",
            "narrowing_rules": [
                {"id": "price_unavailable_for_budget", "narrow_to": "hold", "reason_code": "line_total_unavailable_for_agent_budget"},
                {"id": "over_budget", "narrow_to": "hold", "reason_code": "line_total_exceeds_agent_budget"},
            ],
        }
        with patch("ramify.policy.actor.profiles.profile", return_value=profile):
            decision = actor_policy.apply("allow", "budget-test", subject, {"line_total_cents": None})
        self.assertEqual(decision.decision, "hold")
        self.assertIn("line_total_unavailable_for_agent_budget", decision.reason_codes)
        condition = next(c for c in decision.conditions_evaluated if c["id"] == "price_unavailable_for_budget")
        self.assertFalse(condition["met"])

    def test_alternatives_do_not_route_around_trust_warning(self):
        blocked = engine.assess(
            NORTHBEAM, "autonomous_buyer_v1", context="suggestion", persist_receipt=False
        )
        # Synthetic guard: even if an otherwise suggestible result is held by a
        # trust-derived warning rule, alternatives must not bypass it.
        blocked = copy.deepcopy(blocked)
        blocked["objective_posture"] = "allow_with_warning"
        blocked["actor_decision"] = "hold"
        blocked["requires_human"] = True
        blocked["applied_rules"] = [{"id": "warned_outcome_requires_review", "kind": "trust_derived"}]
        self.assertIsNone(alternatives.find(NORTHBEAM, "autonomous_buyer_v1", 1, blocked))


class FakeAgent:
    def __init__(self, output):
        self.output = output
    def run_sync(self, prompt):
        return SimpleNamespace(output=self.output)


class TestPydanticAIHardening(unittest.TestCase):
    def test_model_cannot_escape_candidate_set(self):
        adapter = PydanticAIAdapter()
        adapter._agent = FakeAgent(json.dumps({"identifier": NORTHBEAM, "confidence": 1, "note": "x"}))
        result = adapter.interpret("apex", [{"subject_ref": APEX}])
        self.assertIsNone(result.identifier)
        self.assertEqual(result.confidence, 0.0)

    def test_model_confidence_is_clamped(self):
        adapter = PydanticAIAdapter()
        adapter._agent = FakeAgent(json.dumps({"identifier": APEX, "confidence": 4.2, "note": "x"}))
        result = adapter.interpret("apex", [{"subject_ref": APEX}])
        self.assertEqual(result.identifier, APEX)
        self.assertEqual(result.confidence, 1.0)

    def test_non_local_provider_is_rejected_before_agent_construction(self):
        adapter = PydanticAIAdapter()
        fake_module = SimpleNamespace(Agent=lambda *a, **k: object())
        with patch.dict(sys.modules, {"pydantic_ai": fake_module}), patch.dict(
            os.environ, {"RAMIFY_PYDANTICAI_MODEL": "openai:gpt-x"}, clear=False
        ):
            with self.assertRaises(ValueError):
                adapter._ensure_agent()

    def test_non_loopback_ollama_is_rejected(self):
        adapter = PydanticAIAdapter()
        fake_module = SimpleNamespace(Agent=lambda *a, **k: object())
        with patch.dict(sys.modules, {"pydantic_ai": fake_module}), patch.dict(
            os.environ,
            {"RAMIFY_PYDANTICAI_MODEL": "ollama:llama3.1", "RAMIFY_OLLAMA_BASE_URL": "http://example.com:11434"},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                adapter._ensure_agent()


class TestTransactionBinding(TempStoreCase):
    def _purchase_receipt(self):
        return engine.assess(APEX, "consumer_v1", context="purchase")["receipt"]

    def test_manual_cart_quantity_edit_is_rejected_at_checkout(self):
        receipt = self._purchase_receipt()
        cart.add(receipt["receipt_id"])
        path = Path(self.temp.name) / cart.CART_NAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["lines"][0]["quantity"] += 1
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(cart.CartRefused):
            cart.checkout()

    def test_manual_cart_price_edit_is_rejected_at_checkout(self):
        receipt = self._purchase_receipt()
        cart.add(receipt["receipt_id"])
        path = Path(self.temp.name) / cart.CART_NAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["lines"][0]["line_total_cents"] += 100
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(cart.CartRefused):
            cart.checkout()

    def test_order_verifier_rechecks_linked_receipt_cryptographically(self):
        receipt = self._purchase_receipt()
        cart.add(receipt["receipt_id"])
        order = cart.checkout()
        self.assertTrue(verify_receipt(order)["integrity_verified"])
        ledger = store.ledger_path()
        rows = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
        rows[0]["product_name"] = "tampered linked product"
        ledger.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
        report = verify_receipt(order)
        self.assertFalse(report["integrity_verified"])
        self.assertFalse(report["lines_intact"])

    def test_action_ledger_detects_wrong_receipt_hash_even_if_event_chain_rehashed(self):
        receipt = self._purchase_receipt()
        store.record_action({
            "event_id": "audit-event", "action": "add_to_mock_cart",
            "receipt_ref": receipt["receipt_id"], "receipt_hash": "sha256:" + "0" * 64,
        })
        report = store.verify_action_ledger()
        self.assertFalse(report["valid"])
        self.assertTrue(any("receipt_hash" in p["problem"] for p in report["problems"]))

    def test_expired_decision_keeps_integrity_but_loses_purchase_authority(self):
        receipt = self._purchase_receipt()
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        report = verify_receipt(receipt, now=future)
        self.assertTrue(report["integrity_verified"])
        self.assertFalse(report["purchase_authority_valid"])
        self.assertFalse(report["verified"])


class TestEvidenceHardening(unittest.TestCase):
    def test_impossible_validity_chronology_is_malformed(self):
        record = copy.deepcopy(seed.evidence("ev:apex:gmp"))
        record["valid_from"] = "2026-08-01T00:00:00Z"
        record["expires_at"] = "2026-07-01T00:00:00Z"
        report = checks.evaluate_evidence_freshness(record, seed.snapshot_date())
        self.assertEqual(report["state"], "malformed_record")

    def test_signed_artefact_subject_binding_mismatch_fails(self):
        record = copy.deepcopy(seed.evidence("ev:apex:gmp"))
        record["subject_ref"] = NORTHBEAM
        record["scope"] = {"product_ref": NORTHBEAM}
        report = checks.evaluate_evidence_integrity(record, NORTHBEAM)
        self.assertEqual(report["state"], "artefact_binding_mismatch")

    def test_claim_to_evidence_issuer_binding_mismatch_fails(self):
        subject = copy.deepcopy(seed.subject(APEX))
        subject["claims"][0]["issuer_ref"] = "ramify:demo:issuer:Regulator_AU_demo"
        result = checks.check_claims_and_category(subject)
        self.assertEqual(result.outcome, checks.FAIL)
        self.assertIn("claim_evidence_binding_invalid", result.reason_codes)

    def test_policy_tolerance_treats_small_omega3_difference_as_equal(self):
        group = [
            {"value": "EPA 180mg / DHA 120mg"},
            {"value": "EPA 183mg / DHA 124mg"},
        ]
        conflict, detail = checks._claim_values_conflict("ingredient_claim", group)
        self.assertFalse(conflict, detail)

    def test_policy_tolerance_detects_large_omega3_difference(self):
        group = [
            {"value": "EPA 180mg / DHA 120mg"},
            {"value": "EPA 300mg / DHA 200mg"},
        ]
        conflict, _ = checks._claim_values_conflict("ingredient_claim", group)
        self.assertTrue(conflict)


class TestHumanAndProofPack(TempStoreCase):
    def test_human_successor_action_is_accepted_by_generic_action_gate(self):
        original = engine.assess(NORTHBEAM, "procurement_v1", context="purchase")["receipt"]
        self.assertEqual(original["actor_decision"], "hold")
        review = client.post("/api/v0/receipt/review", json={
            "receipt_id": original["receipt_id"], "outcome": "overridden",
            "reviewer_name": "Test", "reviewer_role": "Approver", "reviewer_note": "test",
        })
        self.assertEqual(review.status_code, 200, review.text)
        successor = review.json()["receipt"]
        self.assertIn("create_mock_requisition", successor["human_authorised_actions"])
        action = client.post("/api/v0/action", json={
            "receipt_ref": successor["receipt_id"], "action": "create_mock_requisition"
        })
        self.assertEqual(action.status_code, 200, action.text)

    def test_quick_proof_pack_contains_and_runs_standalone_verifier(self):
        response = client.get("/api/v0/proof-pack")
        self.assertEqual(response.status_code, 200)
        with tempfile.TemporaryDirectory() as td:
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                names = zf.namelist()
                self.assertIn("verify_receipts.py", names)
                self.assertIn("requirements.txt", names)
                zf.extractall(td)
            result = subprocess.run(
                [sys.executable, "verify_receipts.py"], cwd=td,
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
