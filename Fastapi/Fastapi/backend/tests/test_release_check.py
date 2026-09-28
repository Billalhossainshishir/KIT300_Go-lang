"""Self-tests for release private-key detection."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release_check.py"


def load_script():
    spec = importlib.util.spec_from_file_location("release_check_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_tree():
    tmp = TemporaryDirectory()
    root = Path(tmp.name)
    private = Ed25519PrivateKey.generate()
    secret = private.private_bytes_raw().hex()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    crypto = root / "backend" / "ramify" / "crypto"
    crypto.mkdir(parents=True)
    (crypto / "embedded_pubkeys.py").write_text(
        f'PUBLIC_KEYS = {{"ramify:demo:signer:receipt": "{public}"}}\n', encoding="utf-8"
    )
    return tmp, root, secret


def assert_scan_fails(module, fragment):
    output = io.StringIO()
    with pytest.raises(SystemExit) as caught, redirect_stdout(output):
        module.check_no_private_keys()
    assert caught.value.code == 1
    assert fragment in output.getvalue()


def test_public_key_only_passes():
    tmp, root, _ = fixture_tree()
    try:
        module = load_script(); module.ROOT = root
        module.check_no_private_keys()
    finally:
        tmp.cleanup()


def test_renamed_private_key_is_detected_by_derivation():
    tmp, root, secret = fixture_tree()
    try:
        module = load_script(); module.ROOT = root
        (root / "config.json").write_text(json.dumps({"token": secret}), encoding="utf-8")
        assert_scan_fails(module, "secret for a shipped public key")
    finally:
        tmp.cleanup()


def test_private_named_field_and_private_directory_are_detected():
    tmp, root, secret = fixture_tree()
    try:
        module = load_script(); module.ROOT = root
        (root / "fixtures.json").write_text(json.dumps({"private_hex": secret}), encoding="utf-8")
        assert_scan_fails(module, "field named private")
        (root / "fixtures.json").unlink()
        (root / "seed_private").mkdir()
        (root / "seed_private" / "anything.json").write_text("{}", encoding="utf-8")
        assert_scan_fails(module, "private key directory")
    finally:
        tmp.cleanup()
