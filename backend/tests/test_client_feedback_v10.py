"""Regression checks for the final client-feedback release."""

import unittest

from fastapi.testclient import TestClient

from ramify.api.app import app

client = TestClient(app)


class TestHumanFriendlyReceipt(unittest.TestCase):
    def _held(self) -> dict:
        return client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"},
        ).json()

    def test_human_receipt_is_plain_language_and_signed(self):
        original = self._held()
        response = client.post(
            "/api/v0/receipt/review",
            json={
                "receipt_id": original["receipt_ref"],
                "outcome": "overridden",
                "reviewer_name": "Alex Example",
                "reviewer_role": "Customer approver",
                "reviewer_note": "Accepted once after reading the advisory.",
            },
        )
        self.assertEqual(response.status_code, 200)
        receipt = response.json()["receipt"]
        summary = receipt["human_receipt"]
        self.assertEqual(summary["reviewer"]["name"], "Alex Example")
        self.assertTrue(summary["headline"].strip())
        self.assertTrue(summary["what_ramify_found"].strip())
        self.assertTrue(summary["original_receipt"]["unchanged"])
        self.assertEqual(summary["original_receipt"]["receipt_id"], original["receipt_ref"])
        self.assertIn("simulated transaction only", summary["scope"])
        self.assertIn("what_ramify_found", summary)
        self.assertIn("what_the_agent_did", summary)
        self.assertIn("what_the_person_decided", summary)
        report = client.post("/api/v0/receipt/verify", json=receipt).json()
        self.assertTrue(report["verified"])

    def test_human_receipt_tampering_is_rejected(self):
        original = self._held()
        receipt = client.post(
            "/api/v0/receipt/review",
            json={
                "receipt_id": original["receipt_ref"],
                "outcome": "confirmed",
                "reviewer_name": "Alex Example",
                "reviewer_role": "Customer approver",
            },
        ).json()["receipt"]
        receipt["human_receipt"]["headline"] = "Approved"
        report = client.post("/api/v0/receipt/verify", json=receipt).json()
        self.assertFalse(report["verified"])


class TestActionGateLedger(unittest.TestCase):
    def test_actions_are_hash_linked_and_verifiable(self):
        assessed = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:supp:apex-mg-glyc-120"},
        ).json()
        action = assessed["receipt"]["selected_action"]
        response = client.post(
            "/api/v0/action",
            json={"receipt_ref": assessed["receipt_ref"], "action": action},
        )
        self.assertEqual(response.status_code, 200)
        event = response.json()["event"]
        self.assertIn("event_hash", event)
        self.assertIn("previous_event_hash", event)
        self.assertIsInstance(event["event_sequence"], int)
        report = client.get("/api/v0/actions/verify").json()
        self.assertTrue(report["valid"])
        self.assertGreaterEqual(report["total"], 1)


class TestOrderHumanSummary(unittest.TestCase):
    def test_signed_order_contains_customer_summary(self):
        client.delete("/api/v0/cart")
        assessed = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:supp:apex-mg-glyc-120"},
        ).json()
        client.post("/api/v0/cart/add", json={"receipt_ref": assessed["receipt_ref"]})
        order = client.post("/api/v0/cart/checkout").json()["order"]
        self.assertIn("customer_summary", order)
        self.assertIn("what_was_checked", order["customer_summary"])
        self.assertIn("audit_message", order["customer_summary"])
        self.assertTrue(client.post("/api/v0/receipt/verify", json=order).json()["verified"])



class TestPurchaseIntentReviewQueue(unittest.TestCase):
    HELD_PRODUCT = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"

    def test_explicit_purchase_assessment_can_join_needs_me(self):
        assessed = client.post(
            "/api/v0/assess",
            json={"identifier": self.HELD_PRODUCT, "context": "purchase"},
        ).json()
        self.assertTrue(assessed["requires_human"])
        open_ids = {
            row["receipt_id"] for row in client.get("/api/v0/review/queue").json()["open"]
        }
        self.assertIn(assessed["receipt_ref"], open_ids)

    def test_guided_demo_assessment_never_joins_needs_me(self):
        assessed = client.post(
            "/api/v0/assess",
            json={"identifier": self.HELD_PRODUCT, "context": "guided_demo"},
        ).json()
        self.assertTrue(assessed["requires_human"])
        open_ids = {
            row["receipt_id"] for row in client.get("/api/v0/review/queue").json()["open"]
        }
        self.assertNotIn(assessed["receipt_ref"], open_ids)

    def test_interactive_tour_assessment_never_joins_needs_me(self):
        assessed = client.post(
            "/api/v0/assess",
            json={"identifier": self.HELD_PRODUCT, "context": "interactive_tour"},
        ).json()
        self.assertTrue(assessed["requires_human"])
        open_ids = {
            row["receipt_id"] for row in client.get("/api/v0/review/queue").json()["open"]
        }
        self.assertNotIn(assessed["receipt_ref"], open_ids)

    def test_compare_receipts_never_join_needs_me(self):
        compared = client.post(
            "/api/v0/compare",
            json={"identifier": self.HELD_PRODUCT, "quantity": 1},
        ).json()
        comparison_receipts = {row["receipt_ref"] for row in compared["personas"]}
        open_ids = {
            row["receipt_id"] for row in client.get("/api/v0/review/queue").json()["open"]
        }
        self.assertTrue(comparison_receipts.isdisjoint(open_ids))

if __name__ == "__main__":
    unittest.main()
