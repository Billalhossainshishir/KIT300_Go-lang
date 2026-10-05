#!/usr/bin/env python3
"""Meeting-safe verification demonstration for David Male.

Shows three proofs without permanently changing the project or the user's
normal RAMIFY ledger:
  1. clean evidence -> decision receipt verifies -> basket + checkout work
  2. tampered receipt -> hash/signature verification fails
  3. tampered evidence artefact -> RATIFY detects evidence integrity failure

The evidence artefact is restored byte-for-byte in a finally block.
Mutable RAMIFY state is redirected to a temporary directory for this demo.
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

# Keep the meeting demo isolated from the operator's normal local RAMIFY state.
os.environ.setdefault("RAMIFY_DISABLE_AGENT", "1")


def banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


FAILURES: list[str] = []


def result(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{status}] {label}{suffix}")
    # Printed failures used to leave the exit code at 0, so a broken proof
    # looked like a successful demonstration to anything checking the result.
    if not ok:
        FAILURES.append(label)


def main() -> int:
    FAILURES.clear()
    previous_store = os.environ.get("RAMIFY_DATA_DIR")
    try:
        return _run()
    finally:
        if previous_store is None:
            os.environ.pop("RAMIFY_DATA_DIR", None)
        else:
            os.environ["RAMIFY_DATA_DIR"] = previous_store


def _run() -> int:
    with tempfile.TemporaryDirectory(prefix="ramify-david-demo-") as temp_store:
        os.environ["RAMIFY_DATA_DIR"] = temp_store

        from ramify.action import cart
        from ramify.crypto.sign import verify_receipt
        from ramify.data import seed
        from ramify.engine import assess

        subject_ref = "ramify:demo:supp:apex-mg-glyc-120"
        evidence_ref = "ev:apex:coa"

        banner("1) CLEAN TRUST CHAIN — EVIDENCE -> DECISION -> ACTION")
        clean = assess(
            subject_ref,
            actor_ref="consumer_v1",
            quantity=1,
            context="purchase",
            persist_receipt=True,
        )
        receipt = clean["receipt"]
        verification = verify_receipt(receipt)

        print("Primitive order:", " -> ".join(x["primitive"] for x in clean["call_trace"]))
        print("Product:", clean["product_name"])
        print("Objective posture:", clean["objective_posture"])
        print("Actor decision:", clean["actor_decision"])
        print("Receipt:", clean["receipt_ref"])
        result("receipt hash", verification.get("hash_valid") is True)
        result("RAMIFY Ed25519 signature", verification.get("signature_valid") is True)
        result("receipt integrity", verification.get("integrity_verified") is True)
        result("purchase authority window", verification.get("purchase_authority_valid") is True)

        line = cart.add(clean["receipt_ref"])
        order = cart.checkout()
        order_verification = verify_receipt(order)
        result("Action Gate admitted signed basket line", bool(line.get("receipt_ref")))
        result("checkout produced signed order", order_verification.get("integrity_verified") is True)

        banner("2) RECEIPT TAMPER — RECEIPT INTEGRITY FAILS")
        tampered_receipt = deepcopy(receipt)
        original_name = tampered_receipt.get("product_name")
        tampered_receipt["product_name"] = f"{original_name} [TAMPERED]"
        tampered_report = verify_receipt(tampered_receipt)
        result("tampered receipt hash rejected", tampered_report.get("hash_valid") is False)
        result("tampered receipt signature rejected", tampered_report.get("signature_valid") is False)
        result("tampered receipt cannot be trusted", tampered_report.get("integrity_verified") is False)
        for check in tampered_report.get("checks", []):
            if not check.get("passed"):
                print(f"  reason: {check['name']}: {check['detail']}")

        banner("3) EVIDENCE TAMPER — RATIFY EVIDENCE INTEGRITY FAILS")
        evidence = seed.evidence(evidence_ref)
        artefact_path = (seed.DATA_DIR / evidence["storage_path"]).resolve()
        original_bytes = artefact_path.read_bytes()
        try:
            artefact_path.write_bytes(original_bytes + b"\nTAMPERED FOR DAVID DEMO\n")
            tampered_evidence_result = assess(
                subject_ref,
                actor_ref="consumer_v1",
                quantity=1,
                context="decision",
                persist_receipt=False,
            )
            print("Objective posture after evidence tamper:", tampered_evidence_result["objective_posture"])
            print("Actor decision after evidence tamper:", tampered_evidence_result["actor_decision"])
            print("Reason codes:", ", ".join(tampered_evidence_result["reason_codes"]))

            integrity_findings = []
            for check in tampered_evidence_result["receipt"].get("check_results", []):
                for finding in check.get("findings", []):
                    if finding.get("integrity_state") and finding.get("integrity_state") != "verified":
                        integrity_findings.append(finding)
            # Some releases carry the integrity state in evidence findings under a
            # slightly different field layout. The reason code remains authoritative.
            reason_codes = set(tampered_evidence_result.get("reason_codes", []))
            detected = "evidence_hash_mismatch" in reason_codes
            result("RATIFY detected changed evidence bytes", detected)
            if integrity_findings:
                for finding in integrity_findings[:3]:
                    print("  finding:", finding)
            else:
                print("  detected by reason code: evidence_hash_mismatch")
        finally:
            artefact_path.write_bytes(original_bytes)

        result("evidence artefact restored byte-for-byte", artefact_path.read_bytes() == original_bytes)

        banner("4) RECOVERY — ORIGINAL EVIDENCE PASSES AGAIN")
        recovered = assess(
            subject_ref,
            actor_ref="consumer_v1",
            quantity=1,
            context="decision",
            persist_receipt=False,
        )
        result(
            "restored evidence returns clean objective result",
            recovered["objective_posture"] == "allow",
            f"objective={recovered['objective_posture']}, actor={recovered['actor_decision']}",
        )

        if FAILURES:
            print(f"\nDEMO FAILED: {len(FAILURES)} proof(s) did not hold:")
            for label in FAILURES:
                print(f"  - {label}")
            return 1

        print("\nMeeting message:")
        print("  Evidence integrity is verified BEFORE the trust decision.")
        print("  Receipt integrity is verified AFTER the decision is sealed.")
        print("  The Action Gate only acts on valid signed authority.")
        print("\nDemo completed without modifying the normal RAMIFY ledger.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
