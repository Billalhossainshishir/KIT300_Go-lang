"""Regression tests for the client-final hardening pass."""

import unittest

from fastapi.testclient import TestClient

from ramify.agent import interpreter
from ramify.api.app import VERSION, app
from ramify.action import cart
from ramify.crypto import keys
from ramify.crypto.sign import seal
from ramify.receipt import builder, store

client = TestClient(app)
CLEAN = "ramify:demo:supp:apex-mg-glyc-120"
HELD = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"


class TestPurchaseAuthorityBoundaries(unittest.TestCase):
    def setUp(self):
        cart.clear()

    def test_exploratory_receipt_cannot_enter_cart(self):
        result = client.post(
            "/api/v0/assess",
            json={"identifier": CLEAN, "context": "guided_demo"},
        ).json()
        response = client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        self.assertEqual(response.status_code, 409)
        self.assertIn("exploratory", response.json()["detail"])

    def test_exploratory_receipt_cannot_create_action_event(self):
        result = client.post(
            "/api/v0/assess",
            json={"identifier": CLEAN, "context": "interactive_tour"},
        ).json()
        response = client.post(
            "/api/v0/action",
            json={"receipt_ref": result["receipt_ref"], "action": result["selected_action"]},
        )
        self.assertEqual(response.status_code, 409)

    def test_clean_receipt_cannot_be_sent_to_human_review(self):
        result = client.post("/api/v0/assess", json={"identifier": CLEAN}).json()
        response = client.post(
            "/api/v0/receipt/review",
            json={"receipt_id": result["receipt_ref"], "outcome": "overridden"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("does not require", response.json()["detail"])

    def test_same_review_cannot_be_answered_twice(self):
        result = client.post("/api/v0/assess", json={"identifier": HELD}).json()
        first = client.post(
            "/api/v0/receipt/review",
            json={"receipt_id": result["receipt_ref"], "outcome": "confirmed"},
        )
        second = client.post(
            "/api/v0/receipt/review",
            json={"receipt_id": result["receipt_ref"], "outcome": "overridden"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)

    def test_one_receipt_cannot_be_reused_for_multiple_lines(self):
        result = client.post("/api/v0/assess", json={"identifier": CLEAN}).json()
        first = client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        second = client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertIn("already been used", second.json()["detail"])

    def test_used_receipt_cannot_be_reused_after_checkout(self):
        result = client.post("/api/v0/assess", json={"identifier": CLEAN}).json()
        client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        self.assertEqual(client.post("/api/v0/cart/checkout").status_code, 200)
        reused = client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        self.assertEqual(reused.status_code, 409)


    def test_purchase_authority_requires_complete_signed_order_values(self):
        result = client.post("/api/v0/assess", json={"identifier": CLEAN}).json()
        altered = dict(result["receipt"])
        altered.pop("payload_hash", None)
        altered.pop("signature", None)
        altered.pop("order", None)
        altered["receipt_id"] = builder.new_receipt_id()
        no_order = seal(altered)
        store.append(no_order)
        response = client.post("/api/v0/cart/add", json={"receipt_ref": no_order["receipt_id"]})
        self.assertEqual(response.status_code, 409)
        self.assertIn("signed price/quantity", response.json()["detail"])

    def test_corrupt_local_signer_fails_closed_instead_of_silent_rekey(self):
        keys.install_signer_key()
        target = keys.local_data_store() / "signer_key.json"
        target.write_text("{broken", encoding="utf-8")
        try:
            result = client.post("/api/v0/assess", json={"identifier": CLEAN})
            self.assertEqual(result.status_code, 503)
            self.assertIn("corrupt or unreadable", result.json()["detail"])
        finally:
            target.unlink(missing_ok=True)
            keys.install_signer_key()



class TestDefensiveInputs(unittest.TestCase):
    def test_malformed_receipt_fails_verification_without_server_error(self):
        response = client.post(
            "/api/v0/receipt/verify",
            json={"payload_hash": "sha256:not-a-hash", "expires_at": "not-a-date"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["verified"])

    def test_unknown_request_fields_are_rejected(self):
        response = client.post(
            "/api/v0/assess",
            json={"identifier": CLEAN, "secret_override": "allow"},
        )
        self.assertEqual(response.status_code, 422)

    def test_zero_budget_means_zero_not_unlimited(self):
        response = client.post(
            "/api/v0/agents/preview",
            json={"label": "Zero budget", "budget_limit_cents": 0},
        )
        self.assertEqual(response.status_code, 200)
        profile = response.json()
        self.assertEqual(profile["budget_limit_cents"], 0)
        self.assertTrue(any(rule["id"] == "over_budget" for rule in profile["narrowing_rules"]))

    def test_receipt_list_limit_is_bounded(self):
        self.assertEqual(client.get("/api/v0/receipts?limit=1000000").status_code, 422)
        self.assertEqual(client.get("/api/v0/actions?limit=1000000").status_code, 422)

    def test_ambiguous_catalogue_text_does_not_guess(self):
        reading = interpreter.deterministic_interpret("Stonefield zinc")
        self.assertIsNone(reading["identifier"])
        self.assertGreaterEqual(len(reading["candidates"]), 2)
        self.assertIn("Choose", reading["note"])

    def test_health_reports_the_release_version(self):
        self.assertEqual(VERSION, "11.0.7")
        self.assertEqual(client.get("/healthz").json()["version"], VERSION)

    def test_release_version_is_consistent_across_root_metadata(self):
        from pathlib import Path
        import re

        root = Path(__file__).resolve().parents[2]
        self.assertEqual((root / "VERSION.txt").read_text(encoding="utf-8").strip(), VERSION)
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{VERSION}"', pyproject)
        howto = (root / "HOW_TO_RUN.txt").read_text(encoding="utf-8")
        self.assertIn(f"RAMIFY OS v{VERSION}", howto)

    def test_health_reports_launcher_configuration_without_claiming_actual_bind(self):
        health = client.get("/healthz").json()
        self.assertTrue(health["default_launcher_loopback_only"])
        self.assertIsNone(health["binds_loopback_only"])
        self.assertIsNone(health["makes_outbound_calls"])

    def test_human_successor_gets_its_own_fresh_timestamp(self):
        result = client.post("/api/v0/assess", json={"identifier": HELD}).json()
        reviewed = client.post(
            "/api/v0/receipt/review",
            json={"receipt_id": result["receipt_ref"], "outcome": "confirmed"},
        ).json()["receipt"]
        self.assertEqual(reviewed["timestamp"], reviewed["human_review"]["reviewed_at"])
        self.assertNotEqual(reviewed["receipt_id"], result["receipt_ref"])


if __name__ == "__main__":
    unittest.main()
