"""Build the portable six-receipt RAMIFY Extended Proof Pack."""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from ramify.crypto import keys  # noqa: E402
from ramify.data import seed  # noqa: E402
from ramify.engine import assess  # noqa: E402

OUT_DIR = PROJECT_ROOT / "extended-proof-pack"
SAMPLES = [
    ("allow", "ramify:demo:supp:apex-mg-glyc-120", "consumer_v1"),
    ("hold-advisory", "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z", "consumer_v1"),
    ("warned", "ramify:demo:supp:greenline-ashw-ksm66-90", "consumer_v1"),
    ("block-recall", "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K", "consumer_v1"),
    ("proof-consumer", "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "consumer_v1"),
    ("proof-procurement", "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "procurement_v1"),
]
README = """RAMIFY OS Extended Proof Pack - six-receipt leave-behind

This pack is distinct from the browser Quick Proof Pack. It contains six signed
synthetic decision receipts, an explicit manifest, a standalone verifier and
public verification keys only. It contains no RAMIFY application and no private
signing key.

Verify after extraction:
  python -m pip install -r requirements.txt
  python verify_receipts.py

Successful verification establishes historical sealed-record integrity against
the included public demo keys. It does not confer current purchase authority or
rerun RATIFY against current evidence. Products, sellers, issuers and evidence
are synthetic. SHA-256 and Ed25519 mechanics are real; production key custody is
outside this capstone scope.
"""


def main() -> int:
    if OUT_DIR.exists(): shutil.rmtree(OUT_DIR)
    receipts_dir, trust_dir = OUT_DIR / "receipts", OUT_DIR / "trust"
    receipts_dir.mkdir(parents=True); trust_dir.mkdir(parents=True)
    entries = []
    version = (PROJECT_ROOT / "VERSION.txt").read_text().strip()
    with tempfile.TemporaryDirectory(prefix="ramify-proof-signer-") as temp_store:
        old = os.environ.get("RAMIFY_DATA_DIR"); os.environ["RAMIFY_DATA_DIR"] = temp_store
        try:
            for label, subject_ref, actor_ref in SAMPLES:
                receipt = assess(subject_ref, actor_ref, context="proof_pack", persist_receipt=False)["receipt"]
                path = receipts_dir / f"{label}.json"
                raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
                path.write_bytes(raw)
                entries.append({"filename": f"receipts/{path.name}", "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(), "receipt_id": receipt["receipt_id"]})
            public_keys = keys.public_keys()
        finally:
            if old is None: os.environ.pop("RAMIFY_DATA_DIR", None)
            else: os.environ["RAMIFY_DATA_DIR"] = old
    signer = public_keys.get("ramify:demo:signer:receipt", "")
    fingerprint = "sha256:" + hashlib.sha256(bytes.fromhex(signer)).hexdigest() if signer else None
    manifest = {
        "schema": "ramify-proof-pack-manifest-v1", "pack_type": "extended", "app_version": version,
        "data_snapshot": seed.snapshot_id(), "dataset_digest": seed.dataset_digest(),
        "policy_ref": seed.policy_pack()["policy_ref"], "policy_digest": seed.policy_digest(),
        "verifier_version": "portable-verify-v2", "signer_key_fingerprint": fingerprint,
        "expected_receipts": entries,
        "verification_scope": "Historical sealed-record integrity against included public demonstration keys; not current purchase authority or evidence revalidation.",
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (OUT_DIR / "README.txt").write_text(README)
    (OUT_DIR / "verify_receipts.py").write_text((PROJECT_ROOT / "scripts" / "portable_verify.py").read_text())
    (OUT_DIR / "requirements.txt").write_text("cryptography>=42\n")
    (trust_dir / "public_keys.json").write_text(json.dumps(public_keys, indent=2, sort_keys=True) + "\n")
    archive = PROJECT_ROOT / "RAMIFY-Extended-Proof-Pack.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(OUT_DIR.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                z.write(path, path.relative_to(OUT_DIR))
    result = subprocess.run([sys.executable, "verify_receipts.py"], cwd=OUT_DIR, capture_output=True, text=True)
    print(result.stdout.strip())
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr); return result.returncode
    print(f"Wrote {archive.name}: {len(SAMPLES)} receipts, manifest, standalone verifier, public keys only")
    return 0

if __name__ == "__main__": raise SystemExit(main())
