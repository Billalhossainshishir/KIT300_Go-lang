"""Regression coverage for David Male's 21 September 2026 P1 findings.

These tests exercise the failure modes that must be closed before claiming
complete transaction enforcement: checkout bypass, duplicate/replayed one-time
authority, successor renewal, evidence-binding tamper, hard-stop preservation,
and silent signer rotation after local history exists.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ramify import engine
from ramify.action import cart
from ramify.api.app import app
from ramify.crypto import keys
from ramify.crypto.sign import seal, verify_receipt
from ramify.data import seed
from ramify.ratify import checks

client = TestClient(app)
CLEAN = "ramify:demo:supp:apex-mg-glyc-120"
HELD = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"
RECALLED = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"
MERRIDALE = "ramify:demo:ppe:merridale-faceshield-std"


class TempStoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"RAMIFY_DATA_DIR": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _line_for(self, receipt: dict) -> dict:
        order = receipt["order"]
        return {
            "line_id": "manual-line",
            "subject_ref": receipt["subject_ref"],
            "product_name": receipt.get("product_name", ""),
            "brand": "",
            "quantity": order["quantity"],
            "unit_price_cents": order["unit_price_cents"],
            "line_total_cents": order["line_total_cents"],
            "receipt_ref": receipt["receipt_id"],
            "payload_hash": receipt["payload_hash"],
            "actor_ref": receipt["actor_ref"],
            "actor_label": receipt["actor_label"],
            "objective_posture": receipt["objective_posture"],
            "actor_decision": receipt["actor_decision"],
            "unattended": receipt.get("selected_action") == "purchase_autonomously",
            "human_authorised": bool(receipt.get("human_authorised_actions")),
            "human_review_outcome": (receipt.get("human_review") or {}).get("outcome"),
            "supersedes_receipt": receipt.get("supersedes_receipt"),
            "added_at": "2026-09-21T00:00:00.000000000Z",
        }

    def _write_cart(self, lines: list[dict], orders=None, requisitions=None):
        Path(self.temp.name, cart.CART_NAME).write_text(
            json.dumps({
                "lines": lines,
                "orders": orders or [],
                "requisitions": requisitions or [],
            }),
            encoding="utf-8",
        )


class TestTransactionAuthorityP1(TempStoreCase):
    def test_blocked_receipt_manually_inserted_cannot_checkout(self):
        receipt = engine.assess(RECALLED, "consumer_v1", context="purchase")["receipt"]
        self.assertEqual(receipt["actor_decision"], "block")
        self._write_cart([self._line_for(receipt)])
        with self.assertRaises(cart.CartRefused):
            cart.checkout()

    def test_duplicate_line_cannot_reuse_one_receipt_for_extra_quantity(self):
        receipt = engine.assess(CLEAN, "consumer_v1", context="purchase")["receipt"]
        first = cart.add(receipt["receipt_id"])
        duplicate = dict(first)
        duplicate["line_id"] = "manual-duplicate"
        path = Path(self.temp.name, cart.CART_NAME)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["lines"].append(duplicate)
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(cart.CartRefused):
            cart.checkout()

    def test_consumed_receipt_cannot_be_reinserted_for_second_order(self):
        receipt = engine.assess(CLEAN, "consumer_v1", context="purchase")["receipt"]
        line = cart.add(receipt["receipt_id"])
        first = cart.checkout()
        self.assertEqual(first["line_count"], 1)
        path = Path(self.temp.name, cart.CART_NAME)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["lines"] = [line]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(cart.CartRefused):
            cart.checkout()


    def test_duplicate_authority_order_record_fails_historical_verification(self):
        receipt = engine.assess(CLEAN, "consumer_v1", context="purchase")["receipt"]
        cart.add(receipt["receipt_id"])
        order = cart.checkout()
        malicious = dict(order)
        malicious.pop("payload_hash", None)
        malicious.pop("signature", None)
        malicious["lines"] = [dict(order["lines"][0]), dict(order["lines"][0])]
        malicious["line_count"] = 2
        malicious["item_count"] = order["item_count"] * 2
        malicious["total_cents"] = order["total_cents"] * 2
        malicious = seal(malicious)
        report = verify_receipt(malicious)
        self.assertFalse(report["verified"])
        self.assertFalse(report["lines_intact"])

    def test_human_successor_cannot_be_reviewed_again_before_or_after_consumption(self):
        original = engine.assess(HELD, "consumer_v1", context="purchase")["receipt"]
        review = client.post("/api/v0/receipt/review", json={
            "receipt_id": original["receipt_id"],
            "outcome": "overridden",
            "reviewer_name": "Regression reviewer",
            "reviewer_role": "Approver",
        })
        self.assertEqual(review.status_code, 200, review.text)
        successor = review.json()["receipt"]

        second_review = client.post("/api/v0/receipt/review", json={
            "receipt_id": successor["receipt_id"], "outcome": "overridden"
        })
        self.assertEqual(second_review.status_code, 409)

        cart.add(successor["receipt_id"])
        cart.checkout()
        third_review = client.post("/api/v0/receipt/review", json={
            "receipt_id": successor["receipt_id"], "outcome": "overridden"
        })
        self.assertEqual(third_review.status_code, 409)


class TestEvidenceBindingP1(unittest.TestCase):
    def test_claim_value_change_breaks_signed_evidence_binding(self):
        subject = copy.deepcopy(seed.subject(CLEAN))
        subject["claims"][0]["value"] = "tampered claim value"
        result = checks.check_evidence_freshness(subject)
        self.assertEqual(result.outcome, checks.FAIL)
        self.assertIn("evidence_artefact_binding_mismatch", result.reason_codes)

    def test_record_status_and_valid_from_are_authenticated(self):
        record = copy.deepcopy(seed.evidence("ev:merridale:conformity"))
        record["record_status"] = "active"
        status_result = checks.evaluate_evidence_integrity(record, MERRIDALE)
        self.assertEqual(status_result["state"], "artefact_binding_mismatch")

        record = copy.deepcopy(seed.evidence("ev:apex:gmp"))
        record["valid_from"] = "2026-02-01T00:00:00.000000000Z"
        date_result = checks.evaluate_evidence_integrity(record, CLEAN)
        self.assertEqual(date_result["state"], "artefact_binding_mismatch")

    def test_supported_claim_references_are_authenticated(self):
        record = copy.deepcopy(seed.evidence("ev:apex:coa"))
        record["supports_claim_refs"] = []
        result = checks.evaluate_evidence_integrity(record, CLEAN)
        self.assertEqual(result["state"], "artefact_binding_mismatch")

    def test_revocation_is_not_weakened_by_missing_signature_metadata(self):
        subject = copy.deepcopy(seed.subject(MERRIDALE))
        original = seed.evidence("ev:merridale:conformity")
        broken = copy.deepcopy(original)
        broken.pop("signature", None)

        def fake_evidence(ref: str):
            return broken if ref == broken["ref"] else seed.evidence(ref)

        with patch("ramify.ratify.checks.seed.evidence", side_effect=fake_evidence):
            result = checks.check_evidence_freshness(subject)
        self.assertEqual(result.outcome, checks.FAIL)
        self.assertEqual(result.severity, checks.HARD_STOP)
        self.assertIn("evidence_revoked", result.reason_codes)
        self.assertIn("evidence_integrity_metadata_missing", result.reason_codes)


class TestSignerIdentityP1(TempStoreCase):
    def test_missing_private_signer_with_existing_history_fails_closed(self):
        engine.assess(CLEAN, "consumer_v1", context="purchase")
        target = Path(self.temp.name, "signer_key.json")
        self.assertTrue(target.exists())
        target.unlink()
        with self.assertRaises(keys.SignerKeyError):
            keys.load_signer_private_key()
        self.assertFalse(target.exists(), "missing signer must not be silently replaced")

    def test_reset_preserves_existing_signer_identity(self):
        engine.assess(CLEAN, "consumer_v1", context="purchase")
        key_path = Path(self.temp.name, "signer_key.json")
        before = key_path.read_text(encoding="utf-8")
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "seed.py"), "--reset"],
            cwd=root,
            env={**os.environ, "RAMIFY_DATA_DIR": self.temp.name, "PYTHONPATH": str(root / "backend")},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(key_path.read_text(encoding="utf-8"), before)
        self.assertFalse(Path(self.temp.name, "receipts.jsonl").exists())



if __name__ == "__main__":
    unittest.main()
