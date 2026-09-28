"""Regression coverage for the second Nomaan security integration batch."""

import os
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from ramify import engine
from ramify.api.app import app
from ramify.policy import profiles

client = TestClient(app)
HELD = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"


def _editable(ref):
    return {k: profiles.profile(ref)[k] for k in profiles.EDITABLE_FIELDS}


def test_receipt_seals_purchase_style_and_review_uses_it():
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RAMIFY_DATA_DIR": tmp}):
        receipt = engine.assess(HELD, "procurement_v1", context="purchase")["receipt"]
        assert receipt["actor_purchase_style"] == "requisition"

        body = _editable("procurement_v1")
        body["purchase_style"] = "cart"
        assert client.put("/api/v0/agents/procurement_v1", json=body).status_code == 200

        reviewed = client.post(
            "/api/v0/receipt/review",
            json={
                "receipt_id": receipt["receipt_id"],
                "outcome": "overridden",
                "reviewer_name": "Demo reviewer",
                "reviewer_role": "Reviewer",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        successor = reviewed.json()["receipt"]
        assert successor["human_authorised_actions"] == ["create_mock_requisition"]
        assert successor["human_review"]["identity_verified"] is False
        assert "not authenticated" in successor["human_review"]["reviewer_attestation"]
        assert successor["human_receipt"]["reviewer"]["identity_verified"] is False


def test_legacy_receipt_without_style_cannot_be_authorised():
    from ramify.crypto.sign import seal
    from ramify.receipt import store

    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RAMIFY_DATA_DIR": tmp}):
        receipt = engine.assess(HELD, context="purchase")["receipt"]
        legacy = {k: v for k, v in receipt.items() if k not in {"payload_hash", "signature", "actor_purchase_style"}}
        legacy["receipt_id"] += "-legacy"
        store.append(seal(legacy))
        response = client.post(
            "/api/v0/receipt/review",
            json={
                "receipt_id": legacy["receipt_id"],
                "outcome": "overridden",
                "reviewer_name": "Demo reviewer",
                "reviewer_role": "Reviewer",
            },
        )
        assert response.status_code == 409


def test_custom_agent_cannot_borrow_builtin_name():
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RAMIFY_DATA_DIR": tmp}):
        assert client.post("/api/v0/agents", json={"label": "Consumer shopping agent"}).status_code == 400
        created = client.post("/api/v0/agents", json={"label": "My helper"})
        assert created.status_code == 200
        ref = created.json()["ref"]
        body = _editable(ref)
        body["label"] = "  consumer SHOPPING agent "
        assert client.put(f"/api/v0/agents/{ref}", json=body).status_code == 400
