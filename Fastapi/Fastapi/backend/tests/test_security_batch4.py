"""Regression coverage for transaction authority and signer trust continuity."""
import io
import json
import os
import tempfile
import zipfile
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from ramify import engine
from ramify.action import cart
from ramify.api.app import app
from ramify.crypto import keys
from ramify.crypto.sign import seal, verify_receipt
from ramify.receipt import store

client = TestClient(app)
CLEAN = "ramify:demo:supp:apex-mg-glyc-120"
HELD = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"


def test_historical_order_rechecks_transaction_authority():
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RAMIFY_DATA_DIR": tmp}):
        held = engine.assess(HELD, "consumer_v1", context="purchase")["receipt"]
        line = {
            "subject_ref": held["subject_ref"],
            "product_name": held.get("product_name", ""),
            "quantity": held["order"]["quantity"],
            "line_total_cents": held["order"]["line_total_cents"],
            "receipt_ref": held["receipt_id"],
            "receipt_hash": held["payload_hash"],
            "actor_ref": held["actor_ref"],
            "objective_posture": held["objective_posture"],
            "actor_decision": held["actor_decision"],
            "human_authorised": False,
            "supersedes_receipt": held.get("supersedes_receipt"),
        }
        forged_order = seal({"record_type": "order_record", "lines": [line]})
        report = verify_receipt(forged_order)
        assert report["integrity_verified"] is False
        detail = next(c["detail"] for c in report["checks"] if c["name"] == "lines_intact")
        assert "did not permit this transaction" in detail


def test_explicit_signer_rotation_retains_old_receipt_verification():
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RAMIFY_DATA_DIR": tmp}):
        old_receipt = engine.assess(CLEAN, persist_receipt=False)["receipt"]
        old_fp = keys.signer_fingerprint()
        keys._write_runtime_signer(Ed25519PrivateKey.generate())
        assert keys.signer_fingerprint() != old_fp
        assert old_fp in {keys.fingerprint(raw) for raw in keys.retired_signer_keys()}
        report = verify_receipt(old_receipt)
        assert report["integrity_verified"] is True
        assert report["signer_key_fingerprint"] == old_fp
        detail = next(c["detail"] for c in report["checks"] if c["name"] == "signature_valid")
        assert "retained" in detail


def test_health_verify_and_proof_pack_expose_same_current_signer_fingerprint():
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RAMIFY_DATA_DIR": tmp}):
        receipt = engine.assess(CLEAN)["receipt"]
        expected = keys.signer_fingerprint()
        assert client.get("/healthz").json()["signer_key_fingerprint"] == expected
        assert client.post("/api/v0/receipt/verify", json=receipt).json()["signer_key_fingerprint"] == expected
        pack = zipfile.ZipFile(io.BytesIO(client.get("/api/v0/proof-pack").content))
        readme = pack.read("README.txt").decode("utf-8")
        assert expected in readme
        assert "cannot vouch for its own included signer key" in readme


def test_reset_preserves_signer_history_file():
    import importlib.util
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RAMIFY_DATA_DIR": tmp}):
        engine.assess(CLEAN)
        keys._write_runtime_signer(Ed25519PrivateKey.generate())
        before = keys.retired_signer_keys()
        script = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"
        spec = importlib.util.spec_from_file_location("seed_batch4", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.do_reset()
        assert keys.retired_signer_keys() == before
