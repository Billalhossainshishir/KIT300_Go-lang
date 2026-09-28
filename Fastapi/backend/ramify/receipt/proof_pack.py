"""Signed proof-pack manifest helpers.

The receipt files inside a proof pack are already individually signed.  The
manifest is signed as well so deleting a receipt and editing the expected-file
list cannot turn an incomplete pack into a passing one.
"""
from __future__ import annotations

import base64
import hashlib
import json

from ramify.crypto import keys

SIGNATURE_FIELD = "manifest_signature"


def canonical_manifest(manifest: dict) -> bytes:
    """Canonical bytes covered by the manifest signature."""
    body = {key: value for key, value in manifest.items() if key != SIGNATURE_FIELD}
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sign_manifest(manifest: dict) -> dict:
    """Return a copy of *manifest* signed by this installation's receipt key."""
    body = {key: value for key, value in manifest.items() if key != SIGNATURE_FIELD}
    digest = hashlib.sha256(canonical_manifest(body)).digest()
    signed = dict(body)
    signed[SIGNATURE_FIELD] = base64.b64encode(
        keys.load_signer_private_key().sign(digest)
    ).decode("ascii")
    return signed
