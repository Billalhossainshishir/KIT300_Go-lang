"""Regression coverage for signed proof manifests and release/demo behaviour."""
import importlib.util
import io
import json
import os
import tempfile
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ramify.api.app import app

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[2]


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extracted_quick_pack():
    tmp = tempfile.TemporaryDirectory()
    response = client.get("/api/v0/proof-pack")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall(tmp.name)
    verifier = load_script(Path(tmp.name) / "verify_receipts.py", "packed_verifier")
    verifier.ROOT = Path(tmp.name)
    return tmp, verifier


def test_quick_pack_signed_manifest_verifies_and_detects_manifest_edit():
    tmp, verifier = extracted_quick_pack()
    try:
        with redirect_stdout(io.StringIO()):
            assert verifier.main([]) == 0
        manifest_path = Path(tmp.name) / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest.get("manifest_signature")
        manifest["expected_receipts"] = manifest["expected_receipts"][:-1]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            assert verifier.main([]) == 2
        assert "manifest signature does not verify" in output.getvalue()
    finally:
        tmp.cleanup()


def test_quick_pack_detects_missing_declared_receipt():
    tmp, verifier = extracted_quick_pack()
    try:
        receipt = next((Path(tmp.name) / "receipts").glob("*.json"))
        receipt.unlink()
        output = io.StringIO()
        with redirect_stdout(output):
            assert verifier.main([]) == 2
        assert "missing expected receipt" in output.getvalue()
    finally:
        tmp.cleanup()


def test_live_demo_restores_ramify_data_dir():
    demo = load_script(ROOT / "scripts" / "david_live_verification_demo.py", "demo_batch5")
    previous = os.environ.get("RAMIFY_DATA_DIR")
    os.environ["RAMIFY_DATA_DIR"] = "sentinel-before-demo"
    try:
        with redirect_stdout(io.StringIO()):
            assert demo.main() == 0
        assert os.environ.get("RAMIFY_DATA_DIR") == "sentinel-before-demo"
    finally:
        if previous is None:
            os.environ.pop("RAMIFY_DATA_DIR", None)
        else:
            os.environ["RAMIFY_DATA_DIR"] = previous
