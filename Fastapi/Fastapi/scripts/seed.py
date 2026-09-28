"""The pre-build seed step.

Generates the Ed25519 keypairs, writes a synthetic artefact for every evidence
record, hashes it, and signs the hash with the key of the issuer supposed to
have produced it. The artefacts are invented; the hashes and signatures are
real. What is synthetic is the content, not the cryptography over it.

    python scripts/seed.py            keys and fixtures from scratch
    python scripts/seed.py --reset    wipe the local store, keep the keys
    python scripts/seed.py --rekey    regenerate keys, re-sign every fixture

Reset and rekey are different operations and v0.4.1 item 2 asks that they not
be confused: reset restores a machine, rekey invalidates every receipt ever
issued by this demo.
"""

import argparse
import base64
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ramify.crypto import keys  # noqa: E402
from ramify.data import seed as seed_data  # noqa: E402
from ramify.ratify.evidence_binding import encoded_binding  # noqa: E402

ARTEFACT_DIR = seed_data.GENERATED_DIR / "artefacts"


def _load_raw_seed() -> dict:
    return json.loads(seed_data.SEED_PATH.read_text(encoding="utf-8"))


def _evidence_body(dataset: dict, record: dict) -> bytes:
    subject = dataset["subjects"].get(record["subject_ref"], {})
    claims = list(subject.get("claims", []))
    binding = encoded_binding(record, claims)
    return (
        "RAMIFY synthetic evidence v2\n"
        f"binding-json: {binding}\n"
        "\n"
        f"{record['artefact']}\n"
        "\nSynthetic demonstration artefact. Certifies nothing.\n"
    ).encode("utf-8")


def write_artefacts_and_sign() -> dict[str, dict[str, str]]:
    """Write each artefact, bind its decision metadata, hash it and sign it."""
    dataset = _load_raw_seed()
    ARTEFACT_DIR.mkdir(parents=True, exist_ok=True)

    signatures: dict[str, dict[str, str]] = {}
    for ref, record in sorted(dataset["evidence"].items()):
        body = _evidence_body(dataset, record)
        artefact_path = ARTEFACT_DIR / f"{ref.replace(':', '_')}.txt"
        artefact_path.write_bytes(body)

        digest = hashlib.sha256(body).digest()
        issuer_key = keys.load_issuer_private_key(record["issuer_ref"])
        signatures[ref] = {
            "content_hash": "sha256:" + digest.hex(),
            "signature": base64.b64encode(issuer_key.sign(digest)).decode("ascii"),
            "storage_path": str(artefact_path.relative_to(seed_data.DATA_DIR)),
        }

    seed_data.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    seed_data.EVIDENCE_SIGNATURES_PATH.write_text(
        json.dumps(signatures, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return signatures


def sign_records() -> dict[str, dict[str, dict[str, str]]]:
    """Sign recall-status and seller-authority records with their demo issuers."""
    from ramify.ratify.checks import SELLER_AUTHORITY_ISSUER
    dataset = _load_raw_seed()
    signed = {"statuses": {}, "sellers": {}}
    for kind, records in (("statuses", dataset["statuses"]), ("sellers", dataset["sellers"])):
        for ref, record in sorted(records.items()):
            issuer_ref = record["issuer_ref"] if kind == "statuses" else SELLER_AUTHORITY_ISSUER
            canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            digest = hashlib.sha256(canonical.encode("utf-8")).digest()
            signed[kind][ref] = {
                "issuer_ref": issuer_ref,
                "content_hash": "sha256:" + digest.hex(),
                "signature": base64.b64encode(keys.load_issuer_private_key(issuer_ref).sign(digest)).decode("ascii"),
            }
    seed_data.RECORD_SIGNATURES_PATH.write_text(
        json.dumps(signed, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return signed


def do_seed() -> None:
    if (keys.SEED_PRIVATE_DIR / "keys.json").exists():
        print("Seed material already exists. Use --rekey to replace it.")
        return
    _generate()


def do_rekey() -> None:
    print("Regenerating demo keys. The previous runtime signer public key will be retained for historical verification.")
    _generate()


def _generate() -> None:
    keypairs = keys.generate_keypairs()
    keys.write_seed_material(keypairs)
    print(f"Wrote {len(keypairs)} keypairs to {keys.SEED_PRIVATE_DIR}/keys.json")
    print(f"Wrote public keys to {keys.EMBEDDED_PUBKEYS_PATH.name}")

    seed_data.evidence_signatures.cache_clear()
    seed_data.record_signatures.cache_clear()
    signatures = write_artefacts_and_sign()
    print(f"Signed {len(signatures)} evidence artefacts")
    records = sign_records()
    print(f"Signed {len(records['statuses'])} status and {len(records['sellers'])} seller records")
    print(f"Installed the runtime signing key in {keys.local_data_store()}")


def do_reset() -> None:
    """Reset mutable demo data while preserving the installed signer identity."""
    store = keys.local_data_store()
    store.mkdir(parents=True, exist_ok=True)

    # Validate or create the signer *before* deleting any history. If historical
    # state exists but the private signer is missing/corrupt, this fails closed
    # instead of silently rotating identity and invalidating old receipts.
    keys.load_signer_private_key()

    preserved = set(keys.SIGNER_FILES)
    for child in list(store.iterdir()):
        if child.name in preserved:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    print(f"Reset mutable demo data in {store}; signer identity preserved.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--reset", action="store_true", help="wipe the local store, keep keys")
    group.add_argument("--rekey", action="store_true", help="regenerate keys and fixtures")
    args = parser.parse_args()

    if args.reset:
        do_reset()
    elif args.rekey:
        do_rekey()
    else:
        do_seed()


if __name__ == "__main__":
    main()
