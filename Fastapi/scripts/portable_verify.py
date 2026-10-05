"""Portable verifier embedded in RAMIFY proof packs.

Requires only Python and ``cryptography``. It does not import the RAMIFY
application or require access to the local receipt ledger.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

RAMIFY_SIGNER = "ramify:demo:signer:receipt"
UNSIGNED_FIELDS = {"payload_hash", "signature"}
ROOT = Path(__file__).resolve().parent
MANIFEST_NAME = "MANIFEST.json"
# Must match VERIFIER_VERSION in ramify/receipt/proof_pack.py.
VERIFIER_VERSION = "2"


def _trust_file_problem(public_keys) -> str | None:
    """None if the trust file maps names to 32-byte hex public keys."""
    if not isinstance(public_keys, dict) or not public_keys:
        return "trust/public_keys.json is not a non-empty JSON object"
    for name, value in public_keys.items():
        if not isinstance(name, str) or not isinstance(value, str) or len(value) != 64:
            return f"trust/public_keys.json entry {name!r} is not a 64-character hex key"
        try:
            bytes.fromhex(value)
        except ValueError:
            return f"trust/public_keys.json entry {name!r} is not hex"
    return None


def verify_manifest(root: Path, public_keys: dict[str, str]) -> list[str]:
    """Problems with the pack as a whole: missing, changed, extra or unlisted files.

    Checking only whichever receipts were present let a pack with a receipt
    removed pass. The manifest is signed with the receipts' key, so removing
    a receipt together with its manifest line is caught too.
    """
    path = root / MANIFEST_NAME
    if not path.is_file():
        return [f"{MANIFEST_NAME} is missing, so the pack's completeness cannot be checked"]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"{MANIFEST_NAME} is not valid JSON"]
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict)
            or not isinstance(manifest.get("expected_receipts"), list)):
        return [f"{MANIFEST_NAME} does not have the expected structure"]

    problems: list[str] = []
    body = {k: v for k, v in manifest.items() if k != "signature"}
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_keys[RAMIFY_SIGNER]))
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        key.verify(base64.b64decode(manifest.get("signature", ""), validate=True),
                   hashlib.sha256(canonical).digest())
    except (KeyError, ValueError, TypeError, InvalidSignature):
        problems.append(f"{MANIFEST_NAME} signature does not verify against the pack's signer key")

    if manifest.get("verifier_version") != VERIFIER_VERSION:
        problems.append(f"{MANIFEST_NAME} expects verifier version {manifest.get('verifier_version')!r}, "
                        f"this is {VERIFIER_VERSION!r}")

    files = manifest["files"]
    for name, digest in sorted(files.items()):
        target = (root / name).resolve()
        if ".." in Path(name).parts or Path(name).is_absolute() or root.resolve() not in target.parents:
            problems.append(f"{MANIFEST_NAME} lists an unsafe path {name!r}")
            continue
        if not target.is_file():
            problems.append(f"{name} is listed in the manifest but missing")
            continue
        if "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            problems.append(f"{name} does not match its manifest digest")

    expected = set(manifest["expected_receipts"])
    for name in sorted(expected - set(files)):
        problems.append(f"{MANIFEST_NAME} expects {name} but does not list its digest")
    present = {p.relative_to(root).as_posix() for p in (root / "receipts").glob("*.json")}
    for name in sorted(present - expected):
        problems.append(f"{name} is in the pack but not in the manifest")
    return problems


def _reject_floats(value, path="receipt"):
    if isinstance(value, float):
        raise ValueError(f"float found at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _reject_floats(item, f"{path}[{i}]")


def canonical_bytes(receipt: dict) -> bytes:
    payload = {k: v for k, v in receipt.items() if k not in UNSIGNED_FIELDS}
    _reject_floats(payload)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def verify(path: Path, public_keys: dict[str, str]) -> tuple[bool, str]:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            return False, "receipt is not a JSON object"
        digest = hashlib.sha256(canonical_bytes(receipt)).digest()
        expected_hash = "sha256:" + digest.hex()
        if receipt.get("payload_hash") != expected_hash:
            return False, "payload hash mismatch"
        raw_key = public_keys.get(RAMIFY_SIGNER)
        if not raw_key:
            return False, "RAMIFY signer public key missing"
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(raw_key))
        signature = base64.b64decode(receipt.get("signature", ""), validate=True)
        key.verify(signature, digest)
        unknown = [ref for ref in receipt.get("issuer_refs", []) if ref not in public_keys]
        if unknown:
            return False, "unknown issuer reference(s): " + ", ".join(unknown)
        return True, "hash and Ed25519 signature valid"
    except (OSError, json.JSONDecodeError, ValueError, TypeError, InvalidSignature) as exc:
        return False, type(exc).__name__


def _paths(args: list[str]) -> list[Path]:
    if not args:
        return sorted((ROOT / "receipts").glob("*.json"))
    found: list[Path] = []
    for arg in args:
        path = Path(arg)
        if path.is_dir():
            found.extend(sorted(path.glob("*.json")))
        else:
            found.append(path)
    return found


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    trust_path = ROOT / "trust" / "public_keys.json"
    try:
        public_keys = json.loads(trust_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"FAIL trust/public_keys.json: {type(exc).__name__}")
        return 2
    problem = _trust_file_problem(public_keys)
    if problem:
        print(f"FAIL {problem}")
        return 2
    paths = _paths(argv)
    if not paths and argv:
        print("No receipt JSON files found.")
        return 2

    # The key below came from this pack, so a PASS proves only that the
    # receipts match the key they arrived with. Who signed them is settled by
    # comparing this fingerprint with the one the issuer publishes.
    signer_hex = public_keys.get(RAMIFY_SIGNER) if isinstance(public_keys, dict) else None
    if isinstance(signer_hex, str):
        try:
            fingerprint = "sha256:" + hashlib.sha256(bytes.fromhex(signer_hex)).hexdigest()
        except ValueError:
            fingerprint = "unreadable"
        print(f"Signer key {fingerprint}")
        print("This key came from the pack itself. Compare its fingerprint with the one the")
        print("issuing RAMIFY instance publishes before treating a PASS as proof of who signed.")
        print()
    all_ok = True
    # Verifying the pack as delivered (no arguments) also checks it is complete.
    if not argv:
        problems = verify_manifest(ROOT, public_keys)
        for problem in problems:
            print(f"FAIL {problem}")
        if not problems:
            print(f"PASS {MANIFEST_NAME}: every listed file present and unchanged, nothing extra")
        all_ok = not problems
        if not paths:
            print("FAIL no receipt JSON files found")
            return 2
    for path in paths:
        ok, detail = verify(path, public_keys)
        print(f"{'PASS' if ok else 'FAIL'} {path}: {detail}")
        all_ok &= ok
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
