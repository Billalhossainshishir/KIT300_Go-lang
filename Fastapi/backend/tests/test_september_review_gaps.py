"""Gaps from the September v11.0.6 client review that main had not closed.

The fixes were made on the separate build-v11.0.6 history, which shares no
ancestor with main, so they are ported here rather than merged.
"""

import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from ramify.api import app as app_module
from ramify.api.app import app
from ramify.data import seed
from ramify.ratify import checks
from ramify.receipt import store
from ramify.timing import now

client = TestClient(app)

HELD = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"


class TestProvenanceChronology(unittest.TestCase):
    """Dates that cannot all be true of one document are malformed, whatever
    the snapshot date."""

    AS_AT = "2026-07-24T00:00:00.000000000Z"

    def _state(self, **overrides):
        record = {
            "ref": "ev:test:chronology",
            "claim_ref": "clm:test",
            "subject_ref": "ramify:demo:supp:apex-mg-glyc-120",
            "issuer_ref": "ramify:demo:issuer:Concordia_Labs_AU",
            "issued_at": "2026-01-01T00:00:00.000000000Z",
            "valid_from": "2026-02-01T00:00:00.000000000Z",
            "expires_at": "2027-01-01T00:00:00.000000000Z",
            "retrieved_at": "2026-02-02T00:00:00.000000000Z",
            "record_status": "active",
        }
        record.update(overrides)
        return checks.evaluate_evidence_freshness(record, seed.parse_timestamp(self.AS_AT))

    def test_a_coherent_record_is_current(self):
        self.assertEqual(self._state()["state"], "current")

    def test_taking_effect_before_it_was_issued_is_malformed(self):
        result = self._state(valid_from="2025-06-01T00:00:00.000000000Z")
        self.assertEqual(result["state"], "malformed_record")
        self.assertIn("commencement", result["detail"])

    def test_expiring_at_the_instant_it_takes_effect_is_malformed(self):
        result = self._state(expires_at="2026-02-01T00:00:00.000000000Z")
        self.assertEqual(result["state"], "malformed_record")

    def test_no_shipped_evidence_record_is_malformed(self):
        for ref in seed.seed()["evidence"]:
            record = seed.evidence(ref)
            with self.subTest(evidence=ref):
                state = checks.evaluate_evidence_freshness(record, seed.snapshot_date())["state"]
                self.assertNotEqual(state, "malformed_record")


class TestReviewQueueListsOnlyAnswerableItems(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"RAMIFY_DATA_DIR": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _held_receipt_id(self):
        response = client.post("/api/v0/assess", json={
            "identifier": HELD, "actor_ref": "consumer_v1", "quantity": 1, "context": "purchase",
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["receipt"]["receipt_id"]

    def _open_ids(self):
        return [r["receipt_id"] for r in client.get("/api/v0/review/queue").json()["open"]]

    def test_a_fresh_held_item_is_listed(self):
        self.assertIn(self._held_receipt_id(), self._open_ids())

    def test_a_lapsed_item_is_not_listed_but_stays_in_the_ledger(self):
        receipt_id = self._held_receipt_id()
        later = now() + timedelta(days=2)
        with patch.object(app_module, "now", return_value=later):
            self.assertNotIn(receipt_id, self._open_ids())
            refused = client.post("/api/v0/receipt/review", json={
                "receipt_id": receipt_id, "outcome": "overridden",
            })
        self.assertEqual(refused.status_code, 409)
        self.assertIn(receipt_id, [r["receipt_id"] for r in store.all_receipts()])


if __name__ == "__main__":
    unittest.main()
