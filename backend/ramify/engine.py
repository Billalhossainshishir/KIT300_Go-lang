"""The composition root — the three stages, in order.

    Stage 1  Objective assessment      actor-independent
    Stage 2  Actor policy              may narrow, never widen
    Stage 3  Action Gate               simulated action only
             |
             receipt, sealed, straight to the interface

Imports no agent framework and never will. A model sits in front of this and
receives a read-only copy of a finished receipt; it is never asked to produce a
verdict, so a hallucinated answer cannot become one. `test_import_boundary.py`
enforces that rather than leaving it as a promise.
"""

import time

from ramify.action import gate
from ramify.data import seed
from ramify.policy import actor as actor_policy, vocabulary
from ramify.ratify import precedence, verify as ratify_verify
from ramify.receipt import builder, store
from ramify.resolve import primitives
from ramify.timing import Stopwatch, to_display_ms

DEFAULT_ACTOR = "consumer_v1"
MAX_TRANSACTION_QUANTITY = 1000

# Presentation only, deliberately kept out of the signed receipt (client
# correction #2, 22 July 2026). The mapping itself lives in policy.vocabulary
# and carries a version, so the machine posture and the wording a person reads
# cannot drift apart (client direction, 5 August 2026).
TRAFFIC_LIGHT = {
    posture: {
        "colour": row["light"],
        "label": row["user_facing"],
        "meaning": row["meaning"],
        "warning": row["carries_warning"],
        "machine_posture": row["machine_posture"],
        "mapping_version": vocabulary.MAPPING_VERSION,
    }
    for posture, row in vocabulary.POSTURE_MAPPING.items()
}

UNKNOWN_LIGHT = TRAFFIC_LIGHT["escalate"]


def traffic_light(decision: str) -> dict:
    return TRAFFIC_LIGHT.get(decision, UNKNOWN_LIGHT)


# Why a handover happened, which is not the same question as whether one did.
# A recall and a line over budget both stop the agent and are not the same
# event. Presentation, like the light: derived from the receipt, never in it.
ESCALATION_KINDS = (
    (
        "safety",
        (
            "active_recall_on_batch",
            "active_advisory_on_batch",
            "claim_rejected_or_revoked",
            # A withdrawn certificate is a statement about the product, not a
            # gap in the filing, so it belongs here rather than under evidence.
            "evidence_revoked",
        ),
        {
            "headline": "Stopped on a safety finding",
            "body": "Something is recorded against this product itself. This is the one kind of "
            "stop no buyer setting can wave through.",
            "decided_by": "An authorised reviewer, where review is permitted",
            "tone": "severe",
            "icon": "◈",
        },
    ),
    (
        "identity",
        ("identity_unresolved", "identity_ambiguous", "not_run_identity_unresolved"),
        {
            "headline": "Could not tell what this is",
            "body": "The identifier did not resolve to one product, so there was nothing to "
            "check. The agent is saying it does not know, which is different from saying "
            "there is a problem.",
            "decided_by": "Whoever can confirm which product was meant",
            "tone": "unknown",
            "icon": "◇",
        },
    ),
    (
        "integrity",
        (
            "evidence_integrity_metadata_missing",
            "evidence_artefact_missing",
            "evidence_issuer_key_unknown",
            "evidence_storage_path_invalid",
            "evidence_hash_mismatch",
            "evidence_signature_invalid",
            "evidence_subject_scope_mismatch",
            "evidence_artefact_binding_mismatch",
            "claim_evidence_binding_invalid",
        ),
        {
            "headline": "Evidence integrity could not be established",
            "body": "RAMIFY could not reproduce the evidence trust chain from artefact bytes, hash, issuer signature and subject/scope binding. The system stops rather than treating unverified evidence as trusted.",
            "decided_by": "An authorised reviewer or evidence source administrator",
            "tone": "severe",
            "icon": "◆",
        },
    ),
    (
        "evidence",
        (
            "evidence_expired",
            "evidence_not_yet_valid",
            "evidence_expiry_not_supplied",
            "evidence_issuer_inactive",
            "evidence_required_fields_missing",
            "mandatory_evidence_missing",
            "required_claim_missing",
            "issuers_state_conflicting_values",
            "claim_asserted_outside_issuer_authority",
            "no_evidence_to_assess",
            "no_claims_to_compare",
            "status_unknown",
        ),
        {
            "headline": "The paperwork is thin",
            "body": "The product may be perfectly sound. What is missing is current proof of "
            "it, and the agent will not assume the two are the same thing.",
            "decided_by": "Whoever is willing to accept the evidence as it stands",
            "tone": "caution",
            "icon": "◐",
        },
    ),
    (
        "authority",
        (
            "seller_authority_unverified_for_category",
            "seller_authority_revoked",
            "seller_unknown",
        ),
        {
            "headline": "The seller is not established",
            "body": "Nothing here is an allegation against the seller. Their authority to "
            "supply this category simply has not been shown.",
            "decided_by": "Whoever can vouch for the seller",
            "tone": "caution",
            "icon": "◑",
        },
    ),
    (
        "price_unavailable",
        ("line_total_unavailable_for_agent_budget",),
        {
            "headline": "Price unavailable for the spending rule",
            "body": "The product assessment is separate from price. This listing has no usable price, so the agent cannot evaluate its spending ceiling and asks for review instead of pretending it is over budget.",
            "decided_by": "You",
            "tone": "commercial",
            "icon": "◎",
        },
    ),
    (
        "budget",
        ("line_total_exceeds_agent_budget",),
        {
            "headline": "Over your agent's spending limit",
            "body": "The product passed every check. The known line total exceeds the agent's configured spending ceiling.",
            "decided_by": "You",
            "tone": "commercial",
            "icon": "◎",
        },
    ),
    (
        "arrangement",
        (
            "brand_outside_agent_arrangement",
            "seller_not_on_approved_vendor_list",
            "procurement_policy_requires_review_of_warned_outcome",
            "warned_outcome_requires_a_person",
            "autonomy_withheld_on_warned_outcome",
        ),
        {
            "headline": "Outside what your agent may do",
            "body": "This is your own rule, not a finding about the product. The assessment "
            "itself raised nothing that would stop anyone else buying it.",
            "decided_by": "You",
            "tone": "commercial",
            "icon": "◉",
        },
    ),
)

# Reached only if a stop carries a reason code no group claims. A test asserts
# that never happens, so this is a floor rather than a routine outcome.
GENERIC_ESCALATION = {
    "kind": "unspecified",
    "headline": "Stopped, without a classified reason",
    "body": "The agent stopped short of acting. The reason recorded on the receipt has no "
    "plain-English classification, so read the findings below rather than this line.",
    "decided_by": "A person",
    "tone": "caution",
    "icon": "◇",
}

# A rejection is not a handover. The same finding needs different words when
# nobody is being asked anything.
REJECTION_WORDING = {
    "safety": "Rejected on a safety finding",
    "identity": "Rejected — could not tell what this is",
    "integrity": "Rejected — evidence integrity could not be established",
    "evidence": "Rejected on the evidence",
    "authority": "Rejected — the seller is not established",
    "price_unavailable": "Rejected because the price needed by the spending rule is unavailable",
    "budget": "Rejected on your agent's spending limit",
    "arrangement": "Rejected — outside what your agent may do",
    "unspecified": "Rejected, without a classified reason",
}


def escalation_for(reason_codes: list[str], decision: str) -> dict:
    """Classify a stop by its most serious reason.

    Most serious first, so a line both over budget and under advisory reads as
    a safety stop. Produced for rejections too: nobody is being asked, but
    "rejected" on its own is not an answer.
    """
    codes = set(reason_codes)
    found = dict(GENERIC_ESCALATION, matched_reason_codes=[])
    for kind, triggers, description in ESCALATION_KINDS:
        if codes & set(triggers):
            matched = [code for code in reason_codes if code in triggers]
            found = {"kind": kind, "matched_reason_codes": matched, **description}
            break

    requires_human = decision in ("hold", "escalate")
    if not requires_human:
        found = dict(
            found,
            headline=REJECTION_WORDING[found["kind"]],
            decided_by="Nobody — this one is not open to a decision",
            body=found["body"] + " Nothing further will happen automatically.",
        )
    found["requires_human"] = requires_human
    found["decision"] = decision
    return found


def _trace_entry(name: str, summary_in: str, summary_out: str, latency_us: int) -> dict:
    return {
        "primitive": name,
        "input": summary_in,
        "output": summary_out,
        "latency_us": latency_us,
    }


def assess(
    identifier: str,
    actor_ref: str = DEFAULT_ACTOR,
    policy_ref: str | None = None,
    quantity: int = 1,
    context: str = "decision",
    *,
    persist_receipt: bool = True,
    evidence_overrides: dict[str, bytes] | None = None,
) -> dict:
    """Run the full five-primitive cycle and return a sealed receipt.

    `identifier` may be a subject ref, a GTIN, a SKU or a local id. Resolution
    failure is handled rather than assumed away: an unrecognised identifier
    produces an `escalate` posture and a receipt saying so, never an approval.

    `quantity` only reaches the actor stage, where a spend ceiling needs a line
    total. How many you are buying says nothing about whether the thing is what
    it claims to be, so it cannot touch the objective assessment.

    `context` separates a shopping decision from exploratory work.

    `persist_receipt` is an internal side-effect boundary. User-facing decisions
    and comparisons are normally persisted, while read-only helpers such as
    alternative discovery and proof-pack generation can assess without silently
    filling the user's Activity ledger. It is keyword-only so existing callers
    cannot change persistence by accident.
    """
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("quantity must be a whole number")
    if quantity < 1 or quantity > MAX_TRANSACTION_QUANTITY:
        raise ValueError(f"quantity must be between 1 and {MAX_TRANSACTION_QUANTITY}")

    full_started_ns = time.perf_counter_ns()
    watch = Stopwatch()
    trace: list[dict] = []

    with watch.stage("identify"):
        identify_result = primitives.identify(identifier)
    subject_ref = identify_result.get("subject_ref") or identifier
    trace.append(
        _trace_entry(
            "identify",
            identifier,
            subject_ref if identify_result["resolved"] else "unresolved",
            watch.latencies_us["identify"],
        )
    )

    with watch.stage("resolve"):
        resolve_record = primitives.resolve(subject_ref)
    trace.append(
        _trace_entry(
            "resolve",
            subject_ref,
            resolve_record["canonical_state"],
            watch.latencies_us["resolve"],
        )
    )

    with watch.stage("status"):
        status_result = primitives.status(subject_ref)
    trace.append(
        _trace_entry(
            "status",
            subject_ref,
            status_result["standing"],
            watch.latencies_us["status"],
        )
    )

    with watch.stage("verify"):
        verify_result = ratify_verify.verify(
            subject_ref, policy_ref, identify_result, status_result,
            artefact_overrides=evidence_overrides,
        )
    reviewed = sum(1 for c in verify_result["check_results"] if c["outcome"] != "pass")
    trace.append(
        _trace_entry(
            "verify",
            f"{len(verify_result['check_results'])} checks",
            f"{reviewed} finding(s)" if reviewed else "all checks passed",
            watch.latencies_us["verify"],
        )
    )

    subject = seed.subject(subject_ref)

    unit_price = seed.price_cents(subject_ref)
    order = {
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_total_cents": None if unit_price is None else unit_price * quantity,
    }

    with watch.stage("assess"):
        check_objects = _rehydrate(verify_result["check_results"])
        outcome = precedence.evaluate(
            check_objects, status_result["standing"], require_complete=True
        )
        decision = actor_policy.apply(outcome.posture, actor_ref, subject, order)
        action_result = gate.select(decision.decision, actor_ref, subject)
    trace.append(
        _trace_entry(
            "assess",
            f"{outcome.posture} under {actor_ref}",
            decision.decision,
            watch.latencies_us["assess"],
        )
    )

    reason_codes = list(outcome.reason_codes)
    for code in decision.reason_codes:
        if code not in reason_codes:
            reason_codes.append(code)
    if action_result.get("substitution"):
        code = action_result["substitution"]["reason_code"]
        if code not in reason_codes:
            reason_codes.append(code)

    # Every latency is final before the receipt is built.
    latencies = dict(watch.latencies_us)
    latencies["total"] = watch.total()

    signing_started_ns = time.perf_counter_ns()
    receipt = builder.build(
        subject_ref=subject_ref,
        product_name=resolve_record.get("product_name") or identify_result.get("product_name"),
        resolve_record=resolve_record,
        status_result=status_result,
        verify_result=verify_result,
        precedence_outcome=outcome.as_dict(),
        actor_decision=decision.as_dict(),
        action_result=action_result,
        reason_codes=reason_codes,
        latencies_us=latencies,
        call_trace=trace,
        order=order,
        context=context,
    )
    signing_us = max(0, (time.perf_counter_ns() - signing_started_ns) // 1000)
    persistence_us = 0
    if persist_receipt:
        persistence_started_ns = time.perf_counter_ns()
        store.append(receipt)
        persistence_us = max(0, (time.perf_counter_ns() - persistence_started_ns) // 1000)
    full_engine_us = max(0, (time.perf_counter_ns() - full_started_ns) // 1000)

    return {
        "subject_ref": subject_ref,
        "product_name": receipt["product_name"],
        "resolved": identify_result["resolved"],
        "objective_posture": outcome.posture,
        "objective_light": traffic_light(outcome.posture),
        "actor_decision": decision.decision,
        "actor_label": decision.actor_label,
        "narrowed": decision.narrowed,
        "traffic_light": traffic_light(decision.decision),
        "conditions_evaluated": decision.conditions_evaluated,
        "applied_rules": decision.applied_rules,
        "reason_codes": reason_codes,
        "selected_action": action_result["selected_action"],
        "selected_action_description": action_result["selected_action_description"],
        "permitted_actions": action_result["permitted_actions"],
        "unattended": action_result["unattended"],
        "requires_human": action_result["requires_human"],
        "escalation": (
            escalation_for(reason_codes, decision.decision)
            if decision.decision in ("hold", "escalate", "block")
            else None
        ),
        "standing_display": vocabulary.describe_standing(status_result["standing"]),
        "primary_reason": outcome.primary_condition,
        "can_add_to_cart": bool(
            set(action_result["permitted_actions"])
            & {"add_to_mock_cart", "purchase_autonomously"}
        ),
        "can_create_requisition": "create_mock_requisition" in action_result["permitted_actions"],
        "substitution": action_result.get("substitution"),
        "order": order,
        "receipt_ref": receipt["receipt_id"],
        "receipt": receipt,
        "call_trace": trace,
        "runtime_timing_ms": {
            "deterministic_evaluation": to_display_ms(latencies["total"]),
            "receipt_build_and_sign": to_display_ms(signing_us),
            "receipt_persistence": to_display_ms(persistence_us),
            "full_engine_call": to_display_ms(full_engine_us),
            "scope_note": "Full HTTP/network/browser time is outside this engine measurement.",
        },
        "display_latency_ms": {
            name: to_display_ms(value) for name, value in latencies.items()
        },
    }


def _rehydrate(check_dicts: list[dict]):
    """CheckResult objects back from their serialised form."""
    from ramify.ratify.checks import CheckResult

    return [
        CheckResult(
            check_id=item["check_id"],
            label=item["label"],
            outcome=item["outcome"],
            severity=item["severity"],
            detail=item["detail"],
            reason_codes=item["reason_codes"],
            evidence_consulted=item["evidence_consulted"],
            findings=item.get("findings", []),
        )
        for item in check_dicts
    ]
