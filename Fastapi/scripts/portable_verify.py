"""Portable RAMIFY proof-pack verifier v2.

Requires only Python and ``cryptography``. A manifest declares the expected
receipts, raw file digests, build/data/policy identity, verifier version and
signer-key fingerprint. Successful verification proves historical sealed-record
integrity against the included public demo keys; it does not confer current
purchase authority or rerun RATIFY against current evidence.
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
VERIFIER_VERSION = "portable-verify-v2"
MANIFEST_SCHEMA = "ramify-proof-pack-manifest-v1"


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
    if not isinstance(receipt, dict):
        raise ValueError("receipt must be a JSON object")
    payload = {k: v for k, v in receipt.items() if k not in UNSIGNED_FIELDS}
    _reject_floats(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _fingerprint(public_hex: str) -> str:
    return "sha256:" + hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()


def _load_json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def verify_receipt_file(path: Path, public_keys: dict[str, str], expected_sha256: str | None = None) -> tuple[bool, str]:
    try:
        raw = path.read_bytes()
        if expected_sha256:
            actual_file = "sha256:" + hashlib.sha256(raw).hexdigest()
            if actual_file != expected_sha256:
                return False, "raw file digest does not match manifest"
        receipt = json.loads(raw.decode("utf-8"))
        if not isinstance(receipt, dict):
            return False, "receipt must be a JSON object"
        digest = hashlib.sha256(canonical_bytes(receipt)).digest()
        if receipt.get("payload_hash") != "sha256:" + digest.hex():
            return False, "payload hash mismatch"
        raw_key = public_keys.get(RAMIFY_SIGNER)
        if not isinstance(raw_key, str) or not raw_key:
            return False, "RAMIFY signer public key missing"
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(raw_key))
        signature = base64.b64decode(receipt.get("signature", ""), validate=True)
        key.verify(signature, digest)
        unknown = [ref for ref in receipt.get("issuer_refs", []) if ref not in public_keys]
        if unknown:
            return False, "unknown issuer reference(s): " + ", ".join(unknown)
        return True, "raw digest, canonical hash and Ed25519 signature valid"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, InvalidSignature) as exc:
        return False, type(exc).__name__ + (f": {exc}" if str(exc) else "")


def _declared_receipts(manifest: dict) -> list[dict]:
    rows = manifest.get("expected_receipts")
    if not isinstance(rows, list) or not rows:
        raise ValueError("manifest expected_receipts must be a non-empty list")
    out = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("filename"), str) or not isinstance(row.get("sha256"), str):
            raise ValueError("each manifest receipt entry needs filename and sha256")
        out.append(row)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        manifest = _load_json_object(ROOT / "manifest.json", "manifest.json")
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise ValueError("unsupported manifest schema")
        if manifest.get("verifier_version") != VERIFIER_VERSION:
            raise ValueError("manifest verifier_version does not match this verifier")
        public_keys = _load_json_object(ROOT / "trust" / "public_keys.json", "trust/public_keys.json")
        signer = public_keys.get(RAMIFY_SIGNER)
        if not isinstance(signer, str) or not signer:
            raise ValueError("RAMIFY signer public key missing")
        if manifest.get("signer_key_fingerprint") != _fingerprint(signer):
            raise ValueError("signer-key fingerprint does not match trust/public_keys.json")
        declared = _declared_receipts(manifest)
    except ValueError as exc:
        print(f"FAIL package metadata: {exc}")
        return 2

    declared_by_name = {row["filename"]: row for row in declared}
    if argv:
        requested: list[Path] = []
        for arg in argv:
            path = Path(arg)
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            if path.is_dir():
                requested.extend(sorted(path.glob("*.json")))
            else:
                requested.append(path)
        targets = []
        for path in requested:
            try:
                rel = path.resolve().relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                print(f"FAIL {path}: file is outside the proof pack")
                return 2
            row = declared_by_name.get(rel)
            if row is None:
                print(f"FAIL {rel}: not declared by manifest")
                return 2
            targets.append((path, row))
    else:
        actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / "receipts").glob("*.json")}
        expected = set(declared_by_name)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing:
            print("FAIL package completeness: missing expected receipt(s): " + ", ".join(missing))
            return 2
        if unexpected:
            print("FAIL package completeness: unexpected receipt(s): " + ", ".join(unexpected))
            return 2
        targets = [(ROOT / name, row) for name, row in declared_by_name.items()]

    all_ok = True
    for path, row in targets:
        ok, detail = verify_receipt_file(path, public_keys, row.get("sha256"))
        print(f"{'PASS' if ok else 'FAIL'} {path.relative_to(ROOT)}: {detail}")
        all_ok &= ok
    if all_ok:
        print("PASS scope: historical sealed-record integrity verified; this does not establish current purchase authority or rerun evidence validity.")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
