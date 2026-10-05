"""Manifests for proof packs.

A pack used to be verified by checking whichever receipt files happened to be
present, so a pack with a receipt removed still passed (David's R2). Each pack
now carries MANIFEST.json: every file's digest, the receipts it must contain,
the build it came from, the verifier version it expects and the signer-key
fingerprint. The manifest is signed with the same key as the receipts, so
removing a receipt and its manifest line together does not go unnoticed.

The portable verifier reads this format without importing RAMIFY.
"""

from __future__ import annotations

import base64
import hashlib
import json

from ramify.crypto import keys
from ramify.data import seed

MANIFEST_NAME = "MANIFEST.json"
MANIFEST_VERSION = 1
# Must match VERIFIER_VERSION in scripts/portable_verify.py.
VERIFIER_VERSION = "2"


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def build_manifest(pack: str, files: dict[str, bytes], build: dict) -> bytes:
    """Signed manifest over ``files`` ({published path: bytes}), excluding itself.

    Call while the store that signed the pack's receipts is active, so the
    manifest is signed by the same key the pack's trust file names.
    """
    body = {
        "manifest_version": MANIFEST_VERSION,
        "pack": pack,
        "verifier_version": VERIFIER_VERSION,
        "build": {
            **build,
            "data_snapshot": seed.snapshot_id(),
            "dataset_digest": seed.dataset_digest(),
            "policy_digest": seed.policy_digest(),
        },
        "signer_key_fingerprint": keys.signer_fingerprint(),
        "files": {
            name: "sha256:" + hashlib.sha256(data).hexdigest()
            for name, data in sorted(files.items())
            if name != MANIFEST_NAME
        },
        "expected_receipts": sorted(name for name in files if name.startswith("receipts/")),
    }
    signature = keys.load_signer_private_key().sign(hashlib.sha256(_canonical(body)).digest())
    body["signature"] = base64.b64encode(signature).decode("ascii")
    return (json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8")
