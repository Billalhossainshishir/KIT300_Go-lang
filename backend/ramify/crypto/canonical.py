"""Canonical form for receipt hashing — spec v0.4 section 8.3.

Signer and verifier both call `canonicalise_receipt`. A one-byte disagreement
between them fails every receipt in the system, so this module has no
dependencies and one entry point.
"""

import json
from datetime import datetime, timezone

UNSIGNED_FIELDS = ("payload_hash", "signature")

# 9 fractional digits, per the RFC3339Nano form the specification names.
_NANO_FORMAT = "%Y-%m-%dT%H:%M:%S"


def rfc3339_nano(moment: datetime | None = None) -> str:
    """RFC3339Nano UTC. Python clocks stop at microseconds, so the last three
    digits are always zero — real zeroes, not padding."""
    moment = moment or datetime.now(timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return f"{moment.strftime(_NANO_FORMAT)}.{moment.microsecond:06d}000Z"


def _reject_floats(value, path: str = "receipt") -> None:
    """No float may enter the canonical form: float serialisation is not
    portable, so a receipt hashed on one machine could fail on another."""
    if isinstance(value, float):
        raise ValueError(
            f"float found at {path}: canonical form carries integers only "
            "(latencies are integer microseconds)"
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")


def canonicalise_receipt(receipt: dict) -> bytes:
    """The exact bytes that get hashed and signed.

    Absent fields are omitted when the receipt is built rather than filtered
    out here — filtering would make "absent" and "present but null" hash
    identically, so a field could be removed without detection.
    """
    payload = {k: v for k, v in receipt.items() if k not in UNSIGNED_FIELDS}
    _reject_floats(payload)
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return canonical.encode("utf-8")
