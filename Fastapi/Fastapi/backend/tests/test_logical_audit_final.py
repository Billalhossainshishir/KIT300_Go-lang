"""Regression tests for the final A-to-Z logical audit.

These tests focus on side effects and semantic boundaries that can look fine in
an interface while still being wrong underneath it.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from fastapi.testclient import TestClient

from ramify import engine
from ramify.action import cart
from ramify.api.app import app
from ramify.receipt import store

client = TestClient(app)
CLEAN = "ramify:demo:supp:apex-mg-glyc-120"
WARNED = "ramify:demo:supp:greenline-ashw-ksm66-90"


class IsolatedState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"RAMIFY_DATA_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class TestDecisionSemantics(IsolatedState):
    def test_warned_allow_is_amber_and_not_an_escalation(self):
        result = engine.assess(WARNED, "consumer_v1")
        self.assertEqual(result["actor_decision"], "allow_with_warning")
        self.assertEqual(result["traffic_light"]["colour"], "orange")
        self.assertTrue(result["traffic_light"]["warning"])
        self.assertIsNone(result["escalation"])

    def test_procurement_requisition_does_not_masquerade_as_cart_authority(self):
        result = engine.assess(CLEAN, "procurement_v1")
        self.assertFalse(result["can_add_to_cart"])
        self.assertTrue(result["can_create_requisition"])
        self.assertIn("create_mock_requisition", result["permitted_actions"])

    def test_procurement_style_never_acquires_autonomous_consumer_checkout(self):
        preview = client.post(
            "/api/v0/agents/preview",
            json={
                "label": "Procurement test",
                "summary": "",
                "autonomy_level": "clean_or_warned",
                "purchase_style": "requisition",
            },
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        profile = preview.json()
        self.assertEqual(profile["autonomy_level"], "none")
        self.assertEqual(profile["auto_purchase_on"], [])
        self.assertIn("create_mock_requisition", profile["permitted_actions"]["allow"])
        self.assertNotIn("purchase_autonomously", profile["permitted_actions"]["allow"])
        self.assertNotIn("add_to_mock_cart", profile["permitted_actions"]["allow"])


class TestExploratorySideEffects(IsolatedState):
    def test_proof_pack_does_not_fill_activity_receipts(self):
        before = len(store.all_receipts())
        response = client.get("/api/v0/proof-pack")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(store.all_receipts()), before)

    def test_proof_pack_readme_uses_a_real_filename_not_a_wildcard_redirect(self):
        response = client.get("/api/v0/proof-pack")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            receipt_names = [name for name in names if name.startswith("receipts/") and name.endswith(".json")]
            self.assertTrue(receipt_names)
            readme = archive.read("README.txt").decode("utf-8")
        self.assertIn(receipt_names[0], readme)
        self.assertNotIn("< receipts\\01_APPROVED_Apex_*.json", readme)

    def test_alternative_discovery_does_not_fill_activity_receipts(self):
        source = engine.assess(WARNED, "budget_guard_v1")
        before = len(store.all_receipts())
        response = client.post(
            "/api/v0/alternatives",
            json={"identifier": source["subject_ref"], "actor_ref": "budget_guard_v1", "quantity": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(store.all_receipts()), before)


class TestRequisitionPath(IsolatedState):
    def test_requisition_is_signed_and_kept_out_of_basket(self):
        result = engine.assess(CLEAN, "procurement_v1", context="purchase")
        response = client.post(
            "/api/v0/requisition/create", json={"receipt_ref": result["receipt_ref"]}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["cart"]["line_count"], 0)
        self.assertEqual(len(body["cart"]["requisitions"]), 1)
        record = body["requisition"]
        self.assertEqual(record["record_type"], "requisition_record")
        report = client.post("/api/v0/receipt/verify", json=record).json()
        self.assertTrue(report["verified"], report["checks"])

    def test_requisition_receipt_cannot_be_replayed_into_basket(self):
        result = engine.assess(CLEAN, "procurement_v1", context="purchase")
        client.post("/api/v0/requisition/create", json={"receipt_ref": result["receipt_ref"]})
        response = client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        self.assertEqual(response.status_code, 409)

    def test_procurement_human_review_preserves_requisition_workflow(self):
        source_ref = "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A"
        result = engine.assess(source_ref, "procurement_v1", context="purchase")
        self.assertEqual(result["actor_decision"], "hold")
        reviewed = client.post(
            "/api/v0/receipt/review",
            json={"receipt_id": result["receipt_ref"], "outcome": "overridden"},
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        successor = reviewed.json()["receipt"]
        self.assertEqual(successor["human_authorised_actions"], ["create_mock_requisition"])
        basket = client.post("/api/v0/cart/add", json={"receipt_ref": successor["receipt_id"]})
        self.assertEqual(basket.status_code, 409)
        requisition = client.post(
            "/api/v0/requisition/create", json={"receipt_ref": successor["receipt_id"]}
        )
        self.assertEqual(requisition.status_code, 200, requisition.text)
        self.assertEqual(requisition.json()["cart"]["line_count"], 0)


class TestActionGateTransactionSemantics(IsolatedState):
    def test_record_action_is_idempotent_for_same_receipt_and_action(self):
        result = engine.assess(CLEAN, "consumer_v1", context="purchase")
        payload = {"receipt_ref": result["receipt_ref"], "action": "add_to_mock_cart"}
        first = client.post("/api/v0/action", json=payload)
        second = client.post("/api/v0/action", json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json().get("already_recorded"))
        events = store.actions_for(result["receipt_ref"])
        self.assertEqual(len([event for event in events if event.get("action") == "add_to_mock_cart"]), 1)

    def test_basket_add_records_the_actual_transaction_event(self):
        result = engine.assess(CLEAN, "consumer_v1", context="purchase")
        response = client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        self.assertEqual(response.status_code, 200, response.text)
        events = store.actions_for(result["receipt_ref"])
        self.assertEqual(len([event for event in events if event.get("action") == "add_to_mock_cart"]), 1)

    def test_requisition_creation_records_requisition_action_only(self):
        result = engine.assess(CLEAN, "procurement_v1", context="purchase")
        response = client.post("/api/v0/requisition/create", json={"receipt_ref": result["receipt_ref"]})
        self.assertEqual(response.status_code, 200, response.text)
        events = store.actions_for(result["receipt_ref"])
        actions = [event.get("action") for event in events]
        self.assertEqual(actions, ["create_mock_requisition"])



class TestAPIBoundaries(IsolatedState):
    def test_guided_comparison_can_pin_the_five_shipped_personas(self):
        created = client.post(
            "/api/v0/agents",
            json={
                "label": "Extra demo agent",
                "summary": "Custom profile",
                "autonomy_level": "none",
                "purchase_style": "cart",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        shipped = [
            "consumer_v1",
            "autonomous_buyer_v1",
            "budget_guard_v1",
            "brand_loyal_v1",
            "procurement_v1",
        ]
        comparison = client.post(
            "/api/v0/compare",
            json={"identifier": CLEAN, "actor_refs": shipped},
        )
        self.assertEqual(comparison.status_code, 200, comparison.text)
        self.assertEqual([row["actor_ref"] for row in comparison.json()["personas"]], shipped)

    def test_unknown_agent_mutations_and_alternative_requests_are_rejected_cleanly(self):
        fields = {
            "label": "Unknown",
            "summary": "Unknown",
            "autonomy_level": "none",
            "purchase_style": "cart",
        }
        self.assertEqual(client.put("/api/v0/agents/not_real", json=fields).status_code, 404)
        self.assertEqual(client.delete("/api/v0/agents/not_real").status_code, 404)
        alternatives = client.post(
            "/api/v0/alternatives",
            json={"identifier": CLEAN, "actor_ref": "not_real", "quantity": 1},
        )
        self.assertEqual(alternatives.status_code, 400)



class TestSubjectEndpoint(IsolatedState):
    def test_subject_evidence_is_unique(self):
        body = client.get(f"/api/v0/subject/{CLEAN}").json()
        refs = [item["ref"] for item in body["evidence"]]
        self.assertEqual(refs, list(dict.fromkeys(refs)))
        self.assertEqual(refs.count("ev:apex:coa"), 1)


class TestHealthWording(IsolatedState):
    def test_health_describes_the_documented_launch_command(self):
        body = client.get("/healthz").json()
        self.assertTrue(body["documented_launch_loopback_only"])
        self.assertIn("documented CMD launch command", body["note"])
        self.assertNotIn("supplied launchers", body["note"])


if __name__ == "__main__":
    unittest.main()
