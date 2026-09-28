"""Verify every receipt in the local ledger. Exits non-zero if any fails, so a
broken canonicaliser cannot pass unnoticed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ramify.crypto.sign import verify_receipt  # noqa: E402
from ramify.receipt import store  # noqa: E402


def main() -> int:
    receipts = store.all_receipts()
    if not receipts:
        print("Ledger is empty. Run the demo, or `make test`, to generate receipts.")
        return 0

    failures = []
    expired = 0
    for receipt in receipts:
        report = verify_receipt(receipt)
        # An old receipt legitimately falls outside its purchase-authority validity window. That
        # is not an integrity failure, so it is counted separately.
        integrity = all(
            report[name]
            for name in ("hash_valid", "signature_valid", "issuer_refs_known", "scope_valid")
        )
        if not integrity:
            failures.append((receipt.get("receipt_id"), report))
        elif not report.get("fresh", True):
            expired += 1

    print(f"{len(receipts)} receipt(s) in {store.ledger_path()}")
    print(f"  integrity intact : {len(receipts) - len(failures)}")
    print(f"  past purchase-authority window      : {expired}")
    print(f"  failed           : {len(failures)}")

    for receipt_id, report in failures:
        print(f"\n{receipt_id}")
        for check in report["checks"]:
            if not check["passed"]:
                print(f"  {check['name']}: {check['detail']}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
