"""Receipt construction and sealing — component 5.

One rule governs this module: the receipt must be complete before it is sealed.
`build` takes finished values and returns a sealed receipt, so there is no path
that writes into one after the hash is computed.

`traffic_light` is deliberately absent — the posture is the decision, the
colour is presentation (client direction, 22 July 2026, item 2).
"""

import uuid
from datetime import timedelta

from ramify.crypto.canonical import rfc3339_nano
from ramify.crypto.sign import seal
from ramify.data import seed
from ramify.timing import now

SCHEMA_VERSION = "0.4"
RECEIPT_TTL_SECONDS = 3600
PINNED_RECEIPT_ID = "ramify:demo:rcpt:0000000000000000000000000000000d"

NOTICE = (
    "Synthetic demonstration data. This receipt records what was checked "
    "against a curated test dataset and certifies nothing in the real world."
)


def new_receipt_id() -> str:
    if seed.deterministic_mode():
        return PINNED_RECEIPT_ID
    return f"ramify:demo:rcpt:{uuid.uuid4().hex}"


def _issuer_refs(check_results: list[dict], claim_results: list[dict], status_result: dict) -> list[str]:
    refs: list[str] = []
    for claim in claim_results:
        if claim.get("issuer_ref"):
            refs.append(claim["issuer_ref"])
    if status_result.get("issuer_ref"):
        refs.append(status_result["issuer_ref"])
    for check in check_results:
        for evidence_ref in check.get("evidence_consulted", []):
            record = seed.evidence(evidence_ref)
            if record and record.get("issuer_ref"):
                refs.append(record["issuer_ref"])
    return sorted(dict.fromkeys(refs))


def build(
    *,
    subject_ref: str,
    product_name: str | None,
    resolve_record: dict,
    status_result: dict,
    verify_result: dict,
    precedence_outcome: dict,
    actor_decision: dict,
    action_result: dict,
    reason_codes: list[str],
    latencies_us: dict[str, int],
    call_trace: list[dict],
    order: dict | None = None,
    context: str = "decision",
    supersedes_receipt: str | None = None,
) -> dict:
    """Assemble a receipt from finished values, then seal it."""
    issued_at = now()
    expires_at = issued_at + timedelta(seconds=RECEIPT_TTL_SECONDS)

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": new_receipt_id(),
        "subject_ref": subject_ref,
        "product_name": product_name or "",
        "data_snapshot": verify_result.get("data_snapshot", seed.snapshot_id()),
        "dataset_digest": verify_result.get("dataset_digest", seed.dataset_digest()),
        "assessment_context": context,
        "policy_ref": verify_result["policy_ref"],
        "policy_digest": verify_result.get("policy_digest", seed.policy_digest()),
        "policy_version": verify_result["policy_version"],
        "policy_status": verify_result["policy_status"],
        "actor_ref": actor_decision["actor_ref"],
        "actor_label": actor_decision["actor_label"],
        "call_trace": call_trace,
        "canonical_state": resolve_record["canonical_state"],
        "check_results": verify_result["check_results"],
        "claim_results": verify_result["claim_results"],
        "status_result": status_result,
        "objective_posture": actor_decision["objective_posture"],
        "objective_matched_rule": precedence_outcome["matched_rule"],
        "primary_reason_rule": precedence_outcome["primary_rule"],
        "primary_reason": precedence_outcome["primary_condition"],
        "matched_conditions": precedence_outcome["matched_conditions"],
        "actor_decision": actor_decision["decision"],
        "actor_narrowed": actor_decision["narrowed"],
        "actor_applied_rules": actor_decision["applied_rules"],
        "actor_conditions": actor_decision["conditions_evaluated"],
        "reason_codes": reason_codes,
        "permitted_actions": action_result["permitted_actions"],
        "selected_action": action_result["selected_action"],
        "issuer_refs": _issuer_refs(
            verify_result["check_results"],
            verify_result["claim_results"],
            status_result,
        ),
        "timestamp": rfc3339_nano(issued_at),
        "expires_at": rfc3339_nano(expires_at),
        "latencies_us": dict(latencies_us),
        "timing_scope": {
            "signed_measurement": "deterministic five-primitive evaluation through Action Gate",
            "excludes": ["receipt signing", "receipt persistence", "HTTP/network/rendering"],
            "note": "Full request timing, when reported, is release evidence outside the signed decision payload.",
        },
        "notice": NOTICE,
    }

    if order and order.get("unit_price_cents") is not None:
        # Integer cents — the canonicaliser refuses a float outright.
        receipt["order"] = {
            "quantity": order["quantity"],
            "unit_price_cents": order["unit_price_cents"],
            "line_total_cents": order["line_total_cents"],
            "currency": "AUD",
        }
    if action_result.get("substitution"):
        receipt["substitution"] = action_result["substitution"]
    if supersedes_receipt:
        receipt["supersedes_receipt"] = supersedes_receipt

    # Nothing may be written into `receipt` past this point.
    return seal(receipt)
