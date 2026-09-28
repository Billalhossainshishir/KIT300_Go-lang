"""Command-line verifier for RAMIFY decision receipts.

This module is installed as ``ramify-verify`` and intentionally shares the
same verification implementation as the HTTP API so the two surfaces cannot
drift apart.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ramify.crypto.sign import verify_receipt

LABELS = {
    "hash_valid": "content hash",
    "signature_valid": "signature",
    "issuer_refs_known": "issuer refs known",
    "issuer_chain_valid": "issuer refs known",
    "scope_valid": "scope",
    "fresh": "purchase-authority window",
}


def render(report: dict, receipt: dict) -> str:
    lines = [
        f"receipt   {receipt.get('receipt_id', '(none)')}",
        f"subject   {receipt.get('subject_ref', '(none)')}",
        f"decision  {receipt.get('actor_decision', '(none)')}"
        f"  (objective {receipt.get('objective_posture', '(none)')})",
        "",
    ]
    width = max(len(label) for label in LABELS.values())
    for check in report["checks"]:
        label = LABELS.get(check["name"], check["name"])
        mark = "ok  " if check["passed"] else "FAIL"
        lines.append(f"  {label:<{width}}  {mark}  {check['detail']}")
    lines.append("")
    lines.append("receipt verified." if report["verified"] else "RECEIPT DID NOT VERIFY.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a RAMIFY receipt from a file or standard input."
    )
    parser.add_argument(
        "receipt", nargs="?", type=Path, help="path to a receipt; omit to read stdin"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    try:
        raw = args.receipt.read_text(encoding="utf-8") if args.receipt else sys.stdin.read()
    except OSError as exc:
        print(f"could not read receipt: {exc}", file=sys.stderr)
        return 2

    try:
        receipt = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(receipt, dict):
        print("receipt JSON must be an object", file=sys.stderr)
        return 2

    report = verify_receipt(receipt)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(report, receipt))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
