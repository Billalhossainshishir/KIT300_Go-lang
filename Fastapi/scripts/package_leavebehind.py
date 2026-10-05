"""Build a portable six-receipt RAMIFY Extended Proof Pack.

The leave-behind deliberately contains no RAMIFY application package or private
signing material.  Verification requires only Python, ``cryptography``, the
receipts, and the public trust material captured into the pack.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from ramify.crypto import keys  # noqa: E402
from ramify.data import seed  # noqa: E402
from ramify.engine import assess  # noqa: E402
from ramify.receipt import proof_pack  # noqa: E402

OUT_DIR = PROJECT_ROOT / "extended-proof-pack"
SAMPLES = [
    ("allow", "ramify:demo:supp:apex-mg-glyc-120", "consumer_v1"),
    ("hold-advisory", "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z", "consumer_v1"),
    ("warned", "ramify:demo:supp:greenline-ashw-ksm66-90", "consumer_v1"),
    ("block-recall", "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K", "consumer_v1"),
    ("proof-consumer", "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "consumer_v1"),
    ("proof-procurement", "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "procurement_v1"),
]

README = """\
RAMIFY OS Extended Proof Pack - six-receipt leave-behind
KIT300 ICT Project, University of Tasmania

WHAT THIS IS

This is the extended six-receipt leave-behind, distinct from the browser Quick
Proof Pack (five representative scenarios).  It contains signed decision
receipts, a narrow standalone verifier, and public verification keys only.
It does not contain the RAMIFY application or any private signing key.

HOW TO VERIFY

    python -m pip install -r requirements.txt
    python verify_receipts.py

You may also verify one file:

    python verify_receipts.py receipts/allow.json

The verifier recomputes the canonical SHA-256 payload hash, verifies the
Ed25519 RAMIFY demonstration signature, and confirms that issuer references are
known to the public trust material captured into this pack.  It verifies sealed
record integrity; it deliberately does not turn an old receipt into current
purchase authority.

Run with no arguments, it also checks MANIFEST.json: every file listed is
present and unchanged, all six expected receipts are there, and nothing extra
has been added.  The manifest is signed with the receipts' key, so removing a
receipt together with its manifest line is detected too.

WHICH KEY SIGNED THIS

The public key travels inside this pack, so a PASS proves the receipts match
the key they arrived with.  The verifier prints that key's fingerprint, which
MANIFEST.json also records.  Compare it with the fingerprint in the agreed
handover record before treating the receipts as issued by RAMIFY.

HOW TO CATCH A CHANGE

Edit one character in a receipt and rerun the verifier.  The payload hash and
signature can no longer both verify.  Tamper-evident means a change is visible,
not that the file is impossible to edit.

THE TWO RECEIPTS WORTH READING TOGETHER

proof-consumer.json and proof-procurement.json describe the same product and
evidence.  Their objective posture is the same.  The procurement actor then
narrows what may happen because its commercial policy differs.  Product truth
does not change with the actor.

WHAT IS SYNTHETIC AND WHAT IS NOT

Products, sellers, issuers and evidence are synthetic.  The cryptographic
operations are real SHA-256 and Ed25519 mechanics, but key custody is not
production-grade.  Not for real purchasing, safety, legal or compliance use.
"""


def main() -> int:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    receipts_dir = OUT_DIR / "receipts"
    trust_dir = OUT_DIR / "trust"
    receipts_dir.mkdir(parents=True)
    trust_dir.mkdir(parents=True)

    # Use an isolated local signer for the generated proof pack so running this
    # packaging script never changes or depends on a user's normal demo store.
    with tempfile.TemporaryDirectory(prefix="ramify-proof-signer-") as temp_store:
        old = os.environ.get("RAMIFY_DATA_DIR")
        os.environ["RAMIFY_DATA_DIR"] = temp_store
        try:
            files: dict[str, bytes] = {}
            for label, subject_ref, actor_ref in SAMPLES:
                receipt = assess(
                    subject_ref,
                    actor_ref,
                    context="proof_pack",
                    persist_receipt=False,
                )["receipt"]
                files[f"receipts/{label}.json"] = (
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n"
                ).encode("utf-8")
            files["README.txt"] = README.encode("utf-8")
            files["verify_receipts.py"] = (PROJECT_ROOT / "scripts" / "portable_verify.py").read_bytes()
            files["requirements.txt"] = b"cryptography>=42\n"
            files["trust/public_keys.json"] = (
                json.dumps(keys.public_keys(), indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            # Signed while this pack's own signer is still the active store, so
            # the manifest and the receipts share one key (David's R2).
            files[proof_pack.MANIFEST_NAME] = proof_pack.build_manifest(
                "RAMIFY Extended Proof Pack",
                files,
                {"version": (PROJECT_ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()},
            )
        finally:
            if old is None:
                os.environ.pop("RAMIFY_DATA_DIR", None)
            else:
                os.environ["RAMIFY_DATA_DIR"] = old

    for name, data in files.items():
        (OUT_DIR / name).parent.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / name).write_bytes(data)

    archive = PROJECT_ROOT / "RAMIFY-Extended-Proof-Pack.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(OUT_DIR.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                bundle.write(path, path.relative_to(OUT_DIR))

    result = subprocess.run(
        [sys.executable, "verify_receipts.py"],
        cwd=OUT_DIR,
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip())
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    print(f"Wrote {archive.name}: {len(SAMPLES)} receipts, standalone verifier, public keys only")
    print(f"Dataset {seed.snapshot_id()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
