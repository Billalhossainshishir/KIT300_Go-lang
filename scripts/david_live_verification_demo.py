#!/usr/bin/env python3
"""Executable client verification proof for the final RAMIFY build.

Every required proof contributes to the process exit code. Mutable RAMIFY state
is redirected to a temporary directory and evidence tampering uses an in-memory
copy, so running the demonstration does not edit shipped evidence or the user's
normal basket/ledger.
"""
from __future__ import annotations

import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("RAMIFY_DISABLE_AGENT", "1")

FAILURES = 0


def banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def result(label: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if not ok:
        FAILURES += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))


def main() -> int:
    global FAILURES
    FAILURES = 0
    with tempfile.TemporaryDirectory(prefix="ramify-david-demo-") as temp_store:
        os.environ["RAMIFY_DATA_DIR"] = temp_store
        from ramify.action import cart
        from ramify.crypto.sign import verify_receipt
        from ramify.data import seed
        from ramify.engine import assess
        from ramify.ratify import checks

        subject_ref = "ramify:demo:supp:apex-mg-glyc-120"
        evidence_ref = "ev:apex:coa"

        banner("1) CLEAN TRUST CHAIN - EVIDENCE -> DECISION -> ACTION")
        clean = assess(subject_ref, actor_ref="consumer_v1", quantity=1, context="purchase")
        receipt = clean["receipt"]
        verification = verify_receipt(receipt)
        result("authoritative primitive order", [x["primitive"] for x in clean["call_trace"]] == ["identify", "resolve", "status", "verify", "assess"])
        result("objective allow", clean["objective_posture"] == "allow")
        result("receipt integrity", verification.get("integrity_verified") is True)
        result("purchase-authority window", verification.get("purchase_authority_valid") is True)
        line = cart.add(clean["receipt_ref"])
        order = cart.checkout()
        result("Action Gate admitted signed line", line.get("receipt_ref") == clean["receipt_ref"])
        result("signed order verifies", verify_receipt(order).get("integrity_verified") is True)

        banner("2) RECEIPT TAMPER - SEALED DECISION FAILS INTEGRITY")
        changed = deepcopy(receipt)
        changed["product_name"] += " [TAMPERED]"
        report = verify_receipt(changed)
        result("tampered receipt hash rejected", report.get("hash_valid") is False)
        result("tampered receipt signature rejected", report.get("signature_valid") is False)
        result("tampered receipt integrity rejected", report.get("integrity_verified") is False)

        banner("3) EVIDENCE TAMPER - ISOLATED BYTE COPY FAILS RATIFY")
        record = seed.evidence(evidence_ref)
        artefact_path = (seed.DATA_DIR / record["storage_path"]).resolve()
        original_bytes = artefact_path.read_bytes()
        tampered_bytes = original_bytes + b"\nRAMIFY SYNTHETIC IN-MEMORY TAMPER PROOF\n"
        integrity = checks.evaluate_evidence_integrity_bytes(record, tampered_bytes, subject_ref)
        result("changed evidence bytes rejected", integrity.get("state") == "hash_mismatch", integrity.get("state", ""))
        tampered = assess(
            subject_ref, actor_ref="consumer_v1", quantity=1, context="guided_demo",
            persist_receipt=False, evidence_overrides={evidence_ref: tampered_bytes},
        )
        result("RATIFY does not allow changed evidence", tampered["objective_posture"] in {"block", "escalate"}, tampered["objective_posture"])
        result("shared evidence never changed", artefact_path.read_bytes() == original_bytes)

        banner("4) RECOVERY")
        recovered = assess(subject_ref, actor_ref="consumer_v1", quantity=1, context="guided_demo", persist_receipt=False)
        result("original evidence still produces clean objective result", recovered["objective_posture"] == "allow")

    print("\n" + ("PASS: all required client proofs succeeded." if FAILURES == 0 else f"FAIL: {FAILURES} required proof(s) failed."))
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
