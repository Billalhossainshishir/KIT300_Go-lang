"""The release check has to catch private signing material, including a key
file that has been renamed. These tests build small trees on disk and point the
script at them, so they exercise the real scan rather than a stand-in."""

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "release_check.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("release_check_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivateKeyDetection(unittest.TestCase):
    def setUp(self):
        self.module = _load_script()
        self.private = Ed25519PrivateKey.generate()
        self.secret_hex = self.private.private_bytes_raw().hex()
        self.public_hex = (
            self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        )
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.module.ROOT = self.root

        crypto = self.root / "backend" / "ramify" / "crypto"
        crypto.mkdir(parents=True)
        (crypto / "embedded_pubkeys.py").write_text(
            f'PUBLIC_KEYS = {{"ramify:demo:signer:receipt": "{self.public_hex}"}}\n',
            encoding="utf-8",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def assert_fails(self, expected_fragment):
        """The script reports by printing and exiting 1, so swallow the print
        to keep the test run readable and assert on the message instead."""
        printed = io.StringIO()
        with self.assertRaises(SystemExit) as caught, redirect_stdout(printed):
            self.module.check_no_private_keys()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn(expected_fragment, printed.getvalue())

    def test_public_key_alone_passes(self):
        """The shipped public key must not be mistaken for a secret."""
        self.module.check_no_private_keys()

    def test_signer_key_file_is_caught_by_name(self):
        (self.root / "demo_runtime_seed").mkdir()
        (self.root / "demo_runtime_seed" / "signer_key.json").write_text("{}", encoding="utf-8")
        self.assert_fails("name reserved")

    def test_seed_private_directory_is_caught(self):
        (self.root / "seed_private").mkdir()
        (self.root / "seed_private" / "anything.json").write_text("{}", encoding="utf-8")
        self.assert_fails("private key directory")

    def test_field_named_private_is_caught(self):
        (self.root / "fixtures.json").write_text(
            json.dumps({"private_hex": self.secret_hex}), encoding="utf-8"
        )
        self.assert_fails("field named private")

    def test_pem_private_block_is_caught(self):
        # Assembled at runtime rather than written out, so this file does not
        # itself contain the marker the release check scans for.
        header = "-----BEGIN " + "PRIVATE KEY" + "-----"
        (self.root / "notes.txt").write_text(
            f"{header}\nMC4CAQAw\n-----END {'PRIVATE KEY'}-----\n", encoding="utf-8"
        )
        self.assert_fails("PEM private key")

    def test_renamed_key_is_caught_by_derivation(self):
        """The point of the arithmetic check: no telltale filename or field
        name, just the secret sitting in an innocuous file."""
        (self.root / "config.json").write_text(
            json.dumps({"token": self.secret_hex}), encoding="utf-8"
        )
        self.assert_fails("secret for a shipped public key")

    def test_unrelated_hex_is_not_flagged(self):
        """A 64-character hex value that is not a shipped key must pass, or the
        check would fail on every content hash in the tree."""
        other = Ed25519PrivateKey.generate().private_bytes_raw().hex()
        (self.root / "hashes.json").write_text(
            json.dumps({"payload_hash": other}), encoding="utf-8"
        )
        self.module.check_no_private_keys()


if __name__ == "__main__":
    unittest.main()
