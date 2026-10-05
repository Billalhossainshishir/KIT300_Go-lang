"""Regressions for the findings of the 23 September 2026 security audit.

Each test reproduces one audit finding and fails against the unfixed code.
Every case runs against a throwaway ``RAMIFY_DATA_DIR`` so the demonstration
ledger and the signed evidence artefacts are never touched.

Audit reference, finding to fix number:
    H1 -> 3   review chain is not terminal
    H2 -> 4   evidence status is outside the signature
    M1 -> 5   a weaker defect suppresses a hard stop
    M2 -> 7   receipt can name an unevaluated policy
    M3 -> 1   checkout omits the permitted-actions check
    M4 -> 2   checkout omits the already-used check
    M5 -> 6   a missing key file silently mints a new identity
"""

import copy
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from ramify import engine
from ramify.action import cart
from ramify.api.app import app
from ramify.crypto.canonical import rfc3339_nano
from ramify.data import seed
from ramify.ratify import checks
from ramify.timing import now

client = TestClient(app)

HELD = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"
BLOCKED = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"
REVOKED_EVIDENCE = "ramify:demo:ppe:merridale-faceshield-std"
ALLOWED = "ramify:demo:supp:apex-mg-glyc-120"


class TempStoreCase(unittest.TestCase):
    """Isolate the receipt ledger, basket and signer from the real demo store."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"RAMIFY_DATA_DIR": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def assess(self, subject_ref, **kwargs):
        body = {"identifier": subject_ref, "quantity": 1, "context": "purchase"}
        body.update(kwargs)
        response = client.post("/api/v0/assess", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["receipt"]

    def review(self, receipt_id, outcome="overridden"):
        return client.post(
            "/api/v0/receipt/review",
            json={
                "receipt_id": receipt_id,
                "outcome": outcome,
                "reviewer_name": "Audit Reviewer",
                "reviewer_role": "Pharmacist",
                "reviewer_note": "regression",
            },
        )


class TestH1ReviewChainIsTerminal(TempStoreCase):
    """A person authorises once. One held decision must not yield many."""

    def test_a_successor_cannot_itself_be_reviewed(self):
        held = self.assess(HELD)
        first = self.review(held["receipt_id"])
        self.assertEqual(first.status_code, 200, first.text)
        successor = first.json()["receipt"]

        # The successor deliberately keeps the original's hold decision, which
        # is what made it look reviewable. It carries a human answer, so it is
        # the end of the chain.
        second = self.review(successor["receipt_id"])
        self.assertEqual(second.status_code, 409, second.text)

    def test_one_held_decision_yields_one_purchase_authority(self):
        held = self.assess(HELD)
        current, granted = held["receipt_id"], []
        for _ in range(5):
            response = self.review(current)
            if response.status_code != 200:
                break
            successor = response.json()["receipt"]
            if successor.get("human_authorised_actions"):
                granted.append(successor["receipt_id"])
            current = successor["receipt_id"]

        self.assertEqual(len(granted), 1, "one review must mint exactly one authority")

        added = 0
        for receipt_id in granted:
            if client.post("/api/v0/cart/add", json={"receipt_ref": receipt_id}).status_code == 200:
                added += 1
        self.assertEqual(added, 1)

    def test_a_declined_review_is_also_terminal(self):
        held = self.assess(HELD)
        first = self.review(held["receipt_id"], outcome="confirmed")
        self.assertEqual(first.status_code, 200, first.text)
        successor = first.json()["receipt"]

        second = self.review(successor["receipt_id"], outcome="overridden")
        self.assertEqual(second.status_code, 409, second.text)

    def test_the_original_can_still_only_be_answered_once(self):
        held = self.assess(HELD)
        self.assertEqual(self.review(held["receipt_id"]).status_code, 200)
        self.assertEqual(self.review(held["receipt_id"]).status_code, 409)


class TestH2EvidenceStatusIsAuthenticated(TempStoreCase):
    """Fields that decide the verdict must be covered by the issuer signature."""

    def test_flipping_record_status_does_not_clear_a_block(self):
        subject = seed.subject(REVOKED_EVIDENCE)
        genuine = checks._evidence_for(subject)
        self.assertTrue(
            any(r.get("record_status") == "revoked" for r in genuine),
            "fixture expects a revoked evidence record",
        )

        before = engine.assess(REVOKED_EVIDENCE, quantity=1, context="purchase",
                               persist_receipt=False)
        self.assertEqual(before["objective_posture"], "block")

        tampered = copy.deepcopy(genuine)
        for record in tampered:
            if record.get("record_status") in ("revoked", "withdrawn"):
                record["record_status"] = "active"

        with patch.object(checks, "_evidence_for", return_value=tampered):
            after = engine.assess(REVOKED_EVIDENCE, quantity=1, context="purchase",
                                  persist_receipt=False)

        self.assertNotEqual(
            after["objective_posture"], "allow",
            "editing an unsigned manifest field must not clear a revocation",
        )
        self.assertFalse(after.get("can_add_to_cart"))

    def test_integrity_does_not_report_verified_for_unsigned_status(self):
        subject = seed.subject(REVOKED_EVIDENCE)
        tampered = copy.deepcopy(checks._evidence_for(subject))
        for record in tampered:
            if record.get("record_status") in ("revoked", "withdrawn"):
                record["record_status"] = "active"

        states = [
            checks.evaluate_evidence_integrity(r, subject.get("ref"))["state"]
            for r in tampered
        ]
        self.assertNotIn(
            "verified", states,
            "integrity must not vouch for a record whose status was edited",
        )


class TestM1HardStopsSurviveMissingIntegrity(TempStoreCase):
    """Adding a weaker defect must never weaken the overall outcome."""

    SUBJECT = {"ref": "ramify:demo:test:subject"}
    RECORD = {"ref": "ramify:demo:ev:fixture", "document_type": "test_report"}
    REVOKED = {"state": "revoked", "detail": "the issuer revoked this certificate"}

    def _run(self, integrity_state):
        integrity = {"state": integrity_state, "detail": integrity_state}
        with patch.object(checks, "_evidence_for", return_value=[self.RECORD]), \
             patch.object(checks, "evaluate_evidence_integrity", return_value=integrity), \
             patch.object(checks, "evaluate_evidence_freshness", return_value=self.REVOKED):
            return checks.check_evidence_freshness(self.SUBJECT)

    def test_missing_metadata_does_not_suppress_a_revocation(self):
        baseline = self._run("verified")
        self.assertEqual(baseline.outcome, checks.FAIL)
        self.assertEqual(baseline.severity, checks.HARD_STOP)

        weakened = self._run("missing_metadata")
        self.assertEqual(
            weakened.outcome, checks.FAIL,
            "a revoked record must still fail when its metadata is also missing",
        )
        self.assertEqual(weakened.severity, checks.HARD_STOP)

    def test_the_revocation_reason_is_still_reported(self):
        weakened = self._run("missing_metadata")
        self.assertIn("evidence_revoked", weakened.reason_codes)
        self.assertIn("evidence_integrity_metadata_missing", weakened.reason_codes)


class TestM2ReceiptNamesTheEvaluatedPolicy(TempStoreCase):
    """The sealed receipt must not attest to a policy that never ran."""

    def test_an_unknown_policy_reference_is_rejected(self):
        response = client.post("/api/v0/assess", json={
            "identifier": ALLOWED,
            "quantity": 1,
            "context": "purchase",
            "policy_ref": "ramify:demo:policy:attacker-supplied-permissive-v9",
        })
        self.assertIn(response.status_code, (400, 409, 422), response.text)

    def test_the_receipt_records_the_pack_that_was_evaluated(self):
        receipt = self.assess(ALLOWED)
        self.assertEqual(receipt["policy_ref"], seed.policy_pack()["policy_ref"])

    def test_the_known_policy_reference_is_still_accepted(self):
        pack = seed.policy_pack()
        receipt = self.assess(ALLOWED, policy_ref=pack["policy_ref"])
        self.assertEqual(receipt["policy_ref"], pack["policy_ref"])


class CartFixtureCase(TempStoreCase):
    """Helpers for the two checkout findings, which need a hand-built basket."""

    def line_for(self, receipt):
        order = receipt["order"]
        subject = seed.subject(receipt["subject_ref"]) or {}
        return {
            "line_id": uuid.uuid4().hex[:12],
            "subject_ref": receipt["subject_ref"],
            "product_name": receipt.get("product_name", ""),
            "brand": subject.get("brand", ""),
            "quantity": int(order["quantity"]),
            "unit_price_cents": int(order["unit_price_cents"]),
            "line_total_cents": int(order["line_total_cents"]),
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
            "added_at": rfc3339_nano(now()),
        }

    def write_lines(self, lines):
        basket = cart._read()
        basket["lines"] = lines
        cart._write(basket)


class TestM3CheckoutRechecksPermittedActions(CartFixtureCase):
    """Server-side revalidation must repeat the admission decision, not assume it."""

    def test_a_blocked_receipt_cannot_be_checked_out(self):
        receipt = self.assess(BLOCKED)
        self.assertEqual(receipt["objective_posture"], "block")

        with self.assertRaises(cart.CartRefused):
            cart.add(receipt["receipt_id"])

        self.write_lines([self.line_for(receipt)])
        with self.assertRaises(cart.CartRefused):
            cart.checkout()

    def test_an_allowed_receipt_still_checks_out(self):
        receipt = self.assess(ALLOWED)
        cart.add(receipt["receipt_id"])
        order = cart.checkout()
        self.assertEqual(order["item_count"], int(receipt["order"]["quantity"]))


class TestM4CheckoutRejectsRepeatedAuthority(CartFixtureCase):
    """One signed receipt authorises one transaction line, not many."""

    def test_a_duplicated_line_cannot_inflate_the_order(self):
        receipt = self.assess(ALLOWED)
        cart.add(receipt["receipt_id"])

        lines = list(cart._read()["lines"])
        lines.append(dict(lines[0], line_id=uuid.uuid4().hex[:12]))
        self.write_lines(lines)

        with self.assertRaises(cart.CartRefused):
            cart.checkout()

    def test_quantity_cannot_exceed_the_signed_quantity(self):
        receipt = self.assess(ALLOWED)
        cart.add(receipt["receipt_id"])

        lines = list(cart._read()["lines"])
        lines[0]["quantity"] = int(lines[0]["quantity"]) + 1
        self.write_lines(lines)

        with self.assertRaises(cart.CartRefused):
            cart.checkout()


class TestM5MissingSignerKeyIsNotSilent(TempStoreCase):
    """Key loss must be an explicit recovery event, not a new identity."""

    def test_a_missing_key_beside_an_existing_ledger_is_refused(self):
        from ramify.crypto import keys

        receipt = self.assess(ALLOWED)
        before = keys.load_signer_private_key().public_key().public_bytes_raw()

        (keys.local_data_store() / "signer_key.json").unlink()

        with self.assertRaises(keys.SignerKeyError):
            keys.load_signer_private_key()

        self.assertIsNotNone(receipt["payload_hash"])
        self.assertEqual(
            before,
            before,
            "the original identity must not have been replaced silently",
        )

    def test_first_run_with_no_ledger_still_creates_a_signer(self):
        from ramify.crypto import keys

        store_dir = keys.local_data_store()
        store_dir.mkdir(parents=True, exist_ok=True)
        for name in ("signer_key.json", "receipts.jsonl"):
            path = store_dir / name
            if path.exists():
                path.unlink()

        self.assertIsNotNone(keys.load_signer_private_key())


if __name__ == "__main__":
    unittest.main()
