"""Sealing and verifying receipts — spec section 8.3.

SHA-256 over the canonical bytes as `sha256:<64 hex>`; Ed25519 over the raw
32-byte digest, not over the hex string; signature base64.

`verify_receipt` reports only the checks it actually performs. Nothing is
asserted without being run.
"""

import base64
import hashlib
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ramify.crypto import keys
from ramify.crypto.canonical import canonicalise_receipt, rfc3339_nano

HASH_PREFIX = "sha256:"
PERMITTED_SCOPES = ("product", "batch", "serial", "jurisdiction")

# Which decision actions may stand behind each kind of transaction record.
# Mirrors cart.BASKET_ACTIONS and the requisition path; defined here because
# cart imports this module.
RECORD_ACTIONS = {
    "order_record": frozenset({"add_to_mock_cart", "purchase_autonomously"}),
    "requisition_record": frozenset({"create_mock_requisition"}),
}


def payload_digest(receipt: dict) -> bytes:
    """The raw 32 bytes that get signed — not the hex string."""
    return hashlib.sha256(canonicalise_receipt(receipt)).digest()


def payload_hash(receipt: dict) -> str:
    return HASH_PREFIX + payload_digest(receipt).hex()


def seal(receipt: dict) -> dict:
    """Hash and sign a finished receipt.

    The receipt must be complete first. Anything written into it afterwards
    changes the canonical bytes, and the stored hash stops describing the
    stored content.
    """
    digest = payload_digest(receipt)
    signature = keys.load_signer_private_key().sign(digest)
    sealed = dict(receipt)
    sealed["payload_hash"] = HASH_PREFIX + digest.hex()
    sealed["signature"] = base64.b64encode(signature).decode("ascii")
    return sealed


def _check_hash(receipt: dict) -> tuple[bool, str]:
    stored = receipt.get("payload_hash")
    if not stored:
        return False, "receipt carries no payload_hash"
    recomputed = payload_hash(receipt)
    if stored != recomputed:
        return False, "content does not match the sealed hash"
    return True, "content matches the sealed hash"


def _check_signature(receipt: dict) -> tuple[bool, str]:
    encoded = receipt.get("signature")
    if not encoded:
        return False, "receipt carries no signature"
    public_key = keys.load_public_key(keys.RAMIFY_SIGNER)
    if public_key is None:
        return False, "no RAMIFY signer public key is embedded in this verifier"
    signature = base64.b64decode(encoded)
    digest = payload_digest(receipt)
    try:
        public_key.verify(signature, digest)
        return True, "Ed25519 signature verifies against the RAMIFY signer key (see signer_key_fingerprint)"
    except (InvalidSignature, ValueError):
        pass
    # A receipt issued before the signer was replaced is still checked against
    # the key that signed it, and the result says so rather than passing it
    # off as the current signer's.
    for retired in keys.retired_signer_keys():
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(retired)).verify(signature, digest)
        except (InvalidSignature, ValueError):
            continue
        return True, (
            "Ed25519 signature verifies against a retired RAMIFY signer key "
            f"{keys.fingerprint(retired)}, not the current one"
        )
    return False, "Ed25519 signature does not verify against the RAMIFY signer key"


def _check_issuer_refs_known(receipt: dict) -> tuple[bool, str]:
    """Every issuer named must resolve to known public trust material.

    Citing none is acceptable only on an `escalate`, where the system is saying
    it could not find enough to judge. Any other posture rests on somebody's
    assertion, so naming nobody is internally inconsistent.
    """
    known = keys.public_keys()
    cited = receipt.get("issuer_refs") or []

    if not cited:
        if receipt.get("objective_posture") == "escalate":
            return True, "no issuers cited, consistent with an incomplete assessment"
        return False, "receipt reaches a conclusion but names no issuer for it"

    unknown = [ref for ref in cited if ref not in known]
    if unknown:
        return False, f"unknown issuer: {', '.join(sorted(unknown))}"
    return True, f"{len(cited)} issuer reference(s) resolve to embedded public trust material"


def _check_scope(receipt: dict) -> tuple[bool, str]:
    """The recorded standing must apply at a scope the subject can carry."""
    status = receipt.get("status_result") or {}
    scope = status.get("scope")
    if scope not in PERMITTED_SCOPES:
        return False, f"unrecognised scope: {scope!r}"
    if scope == "batch" and not status.get("batch_ref"):
        return False, "batch-scoped standing names no batch"
    return True, f"standing applies at {scope} scope"


def _check_freshness(receipt: dict, now: datetime) -> tuple[bool, str]:
    expires_at = receipt.get("expires_at")
    if not expires_at:
        return False, "receipt carries no expiry"
    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if now >= expiry:
        return False, f"expired at {expires_at}"
    minutes = int((expiry - now).total_seconds() // 60)
    return True, f"valid for a further {minutes} minute(s)"


def _check_order_lines(record: dict) -> tuple[bool, str]:
    """Every transaction line must bind to an intact decision receipt.

    Verification does not merely compare a quoted hash. The linked receipt is
    cryptographically re-verified and the transaction-critical line fields are
    compared with the values sealed into that receipt. Historical order
    verification uses receipt *integrity*, not the one-hour purchase window.
    """
    from ramify.receipt import store

    lines = record.get("lines") or []
    if not lines:
        return False, "order record has no lines"

    # A signed order used to verify whenever each line matched some intact
    # receipt, so two copies of one line, or a line for a receipt that only
    # permitted `halt`, passed. The authorisation invariants checkout enforces
    # are now checked again for historical records.
    permitted_for_record = RECORD_ACTIONS.get(record.get("record_type"), frozenset())
    first_use: dict[str, int] = {}

    problems: list[str] = []
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            problems.append(f"line {index} is not an object")
            continue
        ref = line.get("receipt_ref", "")
        if ref in first_use:
            problems.append(
                f"line {index} reuses the receipt already used by line {first_use[ref]}; "
                "one receipt authorises one line"
            )
            continue
        first_use[ref] = index
        receipt = store.get(ref)
        if receipt is None:
            problems.append(f"line {index} names a receipt not in the ledger")
            continue
        granted = set(receipt.get("permitted_actions", [])) | set(receipt.get("human_authorised_actions", []))
        if not granted & permitted_for_record:
            problems.append(
                f"line {index} links to a receipt whose decision did not permit this transaction"
            )
            continue
        report = verify_receipt(receipt)
        if not report.get("integrity_verified"):
            problems.append(f"line {index} links to a receipt whose integrity does not verify")
            continue
        if receipt.get("payload_hash") != line.get("receipt_hash"):
            problems.append(f"line {index} quotes the wrong receipt hash")
            continue

        signed_order = receipt.get("order") or {}
        comparisons = {
            "subject_ref": receipt.get("subject_ref"),
            "product_name": receipt.get("product_name", ""),
            "actor_ref": receipt.get("actor_ref"),
            "objective_posture": receipt.get("objective_posture"),
            "actor_decision": receipt.get("actor_decision"),
            "quantity": signed_order.get("quantity"),
            "line_total_cents": signed_order.get("line_total_cents"),
        }
        for field, expected in comparisons.items():
            if line.get(field) != expected:
                problems.append(f"line {index} {field} does not match its signed receipt")
        expected_human = bool(receipt.get("human_authorised_actions"))
        if bool(line.get("human_authorised", False)) != expected_human:
            problems.append(f"line {index} human-authorisation flag does not match its receipt")
        if line.get("supersedes_receipt") != receipt.get("supersedes_receipt"):
            problems.append(f"line {index} successor linkage does not match its receipt")

    if problems:
        return False, "; ".join(problems[:8])
    return True, f"all {len(lines)} line(s) cryptographically trace to matching decision receipts"


def _safe_check(name: str, check, *args) -> tuple[bool, str]:
    """Turn malformed untrusted receipt input into a failed check, never a 500."""
    try:
        return check(*args)
    except Exception as exc:  # verifier is an input boundary; failure is the result
        return False, f"{name} could not be evaluated: {type(exc).__name__}"


PURCHASE_ACTIONS = frozenset({"add_to_mock_cart", "purchase_autonomously", "create_mock_requisition"})


def permits_purchase(receipt: dict) -> bool:
    """Whether the signed decision, or a sealed human successor, allows buying."""
    permitted = set(receipt.get("permitted_actions") or [])
    permitted.update(receipt.get("human_authorised_actions") or [])
    return bool(permitted & PURCHASE_ACTIONS)


def authority_status(report: dict) -> str:
    """One plain answer for the interface, derived from the separate checks."""
    if not report.get("integrity_verified"):
        return "integrity_failed"
    if report.get("time_window_valid") is None:
        return "not_applicable"
    if not report["time_window_valid"]:
        return "window_closed"
    if not report.get("permits_purchase"):
        return "no_purchase_permitted"
    if report.get("transaction_authority_unused") is False:
        return "already_used"
    if report.get("transaction_authority_unused") is None:
        return "current_unchecked_use"
    return "current"


def verify_receipt(receipt: dict, now: datetime | None = None) -> dict:
    """Verify integrity and, for decision receipts, purchase-authority time.

    ``integrity_verified`` answers whether the sealed record is still authentic
    and internally linked. ``purchase_authority_valid`` additionally requires
    the one-hour transaction window to be open. ``verified`` is retained for
    compatibility: it means purchase authority for decision receipts and
    integrity for transaction records.
    """
    now = now or datetime.now(timezone.utc)

    if not isinstance(receipt, dict):
        receipt = {}

    if receipt.get("record_type") in ("order_record", "requisition_record"):
        results = {
            "hash_valid": _safe_check("hash", _check_hash, receipt),
            "signature_valid": _safe_check("signature", _check_signature, receipt),
            "lines_intact": _safe_check("order lines", _check_order_lines, receipt),
        }
        integrity_names = tuple(results)
        authority_names: tuple[str, ...] = ()
    else:
        results = {
            "hash_valid": _safe_check("hash", _check_hash, receipt),
            "signature_valid": _safe_check("signature", _check_signature, receipt),
            "issuer_refs_known": _safe_check("issuer refs", _check_issuer_refs_known, receipt),
            "scope_valid": _safe_check("scope", _check_scope, receipt),
            "fresh": _safe_check("purchase-authority validity window", _check_freshness, receipt, now),
        }
        integrity_names = ("hash_valid", "signature_valid", "issuer_refs_known", "scope_valid")
        authority_names = ("fresh",)

    report = {name: passed for name, (passed, _) in results.items()}
    # Backward-compatible alias for older UI/tests; new wording is more precise.
    if "issuer_refs_known" in report:
        report["issuer_chain_valid"] = report["issuer_refs_known"]
    report["checks"] = [
        {"name": name, "passed": passed, "detail": detail}
        for name, (passed, detail) in results.items()
    ]
    report["integrity_verified"] = all(results[name][0] for name in integrity_names)
    if authority_names:
        # Four separate questions (David, 1 Oct, item 5). A blocked receipt is
        # authentic and inside its window but permits no purchase, so it must
        # not read as current purchase authority. Whether the authority has
        # already been spent needs the ledger, which this function does not
        # read; the API fills `transaction_authority_unused` in, and an offline
        # verifier leaves it null rather than guessing.
        report["time_window_valid"] = report["integrity_verified"] and all(
            results[name][0] for name in authority_names
        )
        report["permits_purchase"] = permits_purchase(receipt)
        report["transaction_authority_unused"] = None
        report["purchase_authority_valid"] = report["time_window_valid"] and report["permits_purchase"]
        report["verified"] = report["time_window_valid"]
    else:
        report["time_window_valid"] = None
        report["permits_purchase"] = None
        report["transaction_authority_unused"] = None
        report["purchase_authority_valid"] = None
        report["verified"] = report["integrity_verified"]
    report["authority_status"] = authority_status(report)
    report["verified_at"] = rfc3339_nano(now)
    # Which key "signature valid" was measured against. Without it a pass says
    # nothing about who signed, only that the receipt matches some key.
    try:
        report["signer_key_fingerprint"] = keys.signer_fingerprint()
    except Exception:  # an unreadable key store must not turn a result into a crash
        report["signer_key_fingerprint"] = None
    return report

