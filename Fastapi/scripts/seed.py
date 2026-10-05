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

ARTEFACT_DIR = seed_data.GENERATED_DIR / "artefacts"


def _load_raw_seed() -> dict:
    return json.loads(seed_data.SEED_PATH.read_text(encoding="utf-8"))


def write_artefacts_and_sign() -> dict[str, dict[str, str]]:
    """Write each artefact, hash it, sign the hash."""
    dataset = _load_raw_seed()
    ARTEFACT_DIR.mkdir(parents=True, exist_ok=True)

    claims_by_ref = {
        claim["ref"]: claim
        for subject in dataset["subjects"].values()
        for claim in subject.get("claims", [])
    }

    signatures: dict[str, dict[str, str]] = {}
    for ref, record in sorted(dataset["evidence"].items()):
        # Every field that decides a verdict goes into the signed header, so the
        # unsigned manifest cannot change it without the change being detected:
        # validity start, record status, which claims this evidence supports,
        # and each supported claim's state and value. (David's E1.)
        supported = sorted({record.get("claim_ref"), *(record.get("supports_claim_refs") or [])} - {None})
        header = [
            record["type"],
            f"issuer: {record['issuer_ref']}",
            f"subject: {record['subject_ref']}",
            f"issued: {record['issued_at']}",
            f"expires: {record['expires_at']}",
            f"valid_from: {record['valid_from']}",
            f"status: {record['record_status']}",
            f"supports: {', '.join(supported)}",
        ]
        for claim_ref in supported:
            claim = claims_by_ref.get(claim_ref)
            if claim is not None:
                header.append(f"claim-state {claim_ref}: {claim['state']}")
                header.append(f"claim-value {claim_ref}: {claim['value']}")
        body = (
            "\n".join(header) + "\n"
            f"\n{record['artefact']}\n"
            "\nSynthetic demonstration artefact. Certifies nothing.\n"
        ).encode("utf-8")

        artefact_path = ARTEFACT_DIR / f"{ref.replace(':', '_')}.txt"
        artefact_path.write_bytes(body)

        digest = hashlib.sha256(body).digest()
        issuer_key = keys.load_issuer_private_key(record["issuer_ref"])
        signatures[ref] = {
            "content_hash": "sha256:" + digest.hex(),
            "signature": base64.b64encode(issuer_key.sign(digest)).decode("ascii"),
            "storage_path": artefact_path.relative_to(seed_data.DATA_DIR).as_posix(),
        }

    seed_data.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    # newline="\n": on Windows, write_text otherwise produces CRLF files.
    seed_data.EVIDENCE_SIGNATURES_PATH.write_text(
        json.dumps(signatures, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return signatures


def sign_records() -> dict[str, dict[str, dict[str, str]]]:
    """Sign every recall-status and seller-authority record with its issuer.

    These records decide verdicts as directly as evidence does, and were
    trusted as plain JSON until the 26 September audit (N4). Each is hashed as
    canonical JSON and signed; RATIFY verifies the signature before using it.
    """
    from ramify.ratify.checks import SELLER_AUTHORITY_ISSUER

    dataset = _load_raw_seed()
    signed: dict[str, dict[str, dict[str, str]]] = {"statuses": {}, "sellers": {}}
    for kind, records in (("statuses", dataset["statuses"]), ("sellers", dataset["sellers"])):
        for ref, record in sorted(records.items()):
            issuer_ref = record["issuer_ref"] if kind == "statuses" else SELLER_AUTHORITY_ISSUER
            canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            digest = hashlib.sha256(canonical.encode("utf-8")).digest()
            signed[kind][ref] = {
                "issuer_ref": issuer_ref,
                "content_hash": "sha256:" + digest.hex(),
                "signature": base64.b64encode(
                    keys.load_issuer_private_key(issuer_ref).sign(digest)
                ).decode("ascii"),
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
    print("Regenerating keys. Every receipt issued by the previous keys stops verifying.")
    _generate()


def _generate() -> None:
    keypairs = keys.generate_keypairs()
    keys.write_seed_material(keypairs)
    print(f"Wrote {len(keypairs)} keypairs to {keys.SEED_PRIVATE_DIR}/keys.json")
    print(f"Wrote public keys to {keys.EMBEDDED_PUBKEYS_PATH.name}")

    seed_data.evidence_signatures.cache_clear()
    signatures = write_artefacts_and_sign()
    print(f"Signed {len(signatures)} evidence artefacts")
    records = sign_records()
    print(f"Signed {len(records['statuses'])} status and {len(records['sellers'])} seller records")
    print(f"Installed the runtime signing key in {keys.local_data_store()}")


def do_reset() -> None:
    """Clear transaction data from the local store, keeping the signing identity.

    Resetting a machine and rotating its keys are different operations. Reset
    used to delete the whole store, signer included, and a distributed copy
    has no seed material to restore it from, so every reset silently minted a
    new identity and stranded every receipt issued before it.
    """
    store = keys.local_data_store()
    if store.exists():
        for child in store.iterdir():
            if child.name in keys.SIGNER_FILES:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        print(f"Cleared receipts, basket, orders and agent edits from {store}")

    if (store / "signer_key.json").exists():
        keys.load_signer_private_key()
        print(f"Kept the runtime signing key in {store}. Keys unchanged.")
        return

    # No private key: either a genuinely fresh store, or an identity that was
    # lost. Minting one is the explicit recovery step; any previous public key
    # is retained so receipts exported before the loss still verify.
    had_previous = keys._current_signer_public_hex() is not None
    keys.install_signer_key()
    if had_previous:
        print(
            f"No signing key was found, so a new one was generated in {store}. The "
            "previous signer's public key is retained in signer_history.json, so "
            "receipts exported before this reset still verify against it."
        )
    else:
        print(f"Installed a new runtime signing key in {store}.")


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
