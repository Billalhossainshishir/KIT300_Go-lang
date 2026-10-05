"""Turning a sealed receipt into plain English.

Two things matter and neither is the prose. The model gets a deep copy, so it
cannot alter what the system decided even by accident. And there is always an
answer: with no model configured a deterministic summary stands in, which keeps
a slow or absent model off the critical path of a demonstration.
"""

import copy
import re

POSTURE_SENTENCE = {
    "allow": "Every check passed and there is no recall or advisory on record, so the agent may proceed.",
    "allow_with_warning": "The product passed, but with a finding attached that the buyer should see before proceeding.",
    "hold": "There is an active advisory, so the agent stops and a person decides.",
    "escalate": "There was not enough on file to reach a judgement, so the agent stops and a person decides.",
    "block": "A check failed on grounds no policy can soften, so the agent must not proceed.",
}

REASON_SENTENCE = {
    "active_recall_on_batch": "this batch is under an active recall",
    "active_advisory_on_batch": "this batch is under an active advisory",
    "evidence_expired": "the supporting laboratory evidence has passed its validity date",
    "seller_authority_unverified_for_category": "the seller's authority to supply this category has not been established",
    "seller_authority_revoked": "the seller's supply authority has been revoked",
    "claim_rejected_or_revoked": "an issuer rejected or withdrew one of the product's claims",
    "claim_asserted_outside_issuer_authority": "a claim was made by an issuer with no registered authority to make it",
    "issuers_state_conflicting_values": "two issuers state different values for the same claim",
    "mandatory_evidence_missing": "evidence this category requires is not attached",
    "required_claim_missing": "no issuer has asserted a claim this category requires",
    "identity_unresolved": "the identifier does not match any known product",
    "identity_ambiguous": "the identifier matches more than one product",
    "status_unknown": "no recall record is held for this product",
    "no_evidence_to_assess": "there is no evidence on file to assess",
    "no_claims_to_compare": "there are no claims on file to compare",
    "superseded_product_available": "a replacement product is available",
    "procurement_policy_requires_review_of_warned_outcome": "procurement policy sends any warned outcome to a person",
    "seller_not_on_approved_vendor_list": "the seller is not on the procurement approved-vendor list",
    "not_run_identity_unresolved": "the remaining checks could not run without a resolved product",
    "status_record_integrity_failed": "the recall status record does not match what the regulator signed",
    "status_record_unsigned": "the recall status record carries no issuer signature",
    "seller_record_integrity_failed": "the seller's authority record does not match what the issuer signed",
    "seller_record_unsigned": "the seller's authority record carries no issuer signature",
}

# Why an agent's own policy tightened the outcome. Kept apart from the product
# findings above: a missing price or a spend ceiling says nothing about the
# product, and a missing price is not the same thing as being over budget.
AGENT_REASON_SENTENCE = {
    "line_total_unavailable_for_agent_budget": (
        "the listing carries no price, so the agent's spend ceiling could not be checked"
    ),
    "line_total_exceeds_agent_budget": "the line total is over the agent's spend ceiling",
    "brand_outside_agent_arrangement": "the brand is outside the agent's arrangement",
    "seller_not_on_approved_vendor_list": "the seller is not on the agent's approved supplier list",
    "autonomy_withheld_on_warned_outcome": "the agent does not buy unattended when a warning is attached",
    "warned_outcome_requires_a_person": "the agent sends warned outcomes to a person",
}


def deterministic_summary(receipt: dict) -> str:
    """Derived from the receipt alone. No model involved."""
    objective = receipt.get("objective_posture", "escalate")
    decision = receipt.get("actor_decision", objective)
    name = receipt.get("product_name") or receipt.get("subject_ref", "this product")

    parts = [f"{name}. {POSTURE_SENTENCE.get(objective, '')}".strip()]

    agent_codes = [
        rule.get("reason_code")
        for rule in receipt.get("actor_applied_rules", [])
        if rule.get("reason_code")
    ]
    reasons = [
        REASON_SENTENCE[code]
        for code in receipt.get("reason_codes", [])
        if code in REASON_SENTENCE and code not in agent_codes
    ]
    if reasons:
        if len(reasons) == 1:
            parts.append(f"The finding was that {reasons[0]}.")
        else:
            listed = "; ".join(reasons[:-1])
            parts.append(f"The findings were that {listed}; and {reasons[-1]}.")

    if receipt.get("actor_narrowed"):
        why = [
            AGENT_REASON_SENTENCE.get(code) or REASON_SENTENCE.get(code)
            for code in agent_codes
        ]
        why = [sentence for sentence in why if sentence]
        because = f" because {'; and '.join(why)}" if why else ""
        parts.append(
            f"Assessed for {receipt.get('actor_label', 'this actor')}, the outcome "
            f"tightens from {objective.replace('_', ' ')} to "
            f"{decision.replace('_', ' ')}{because}. The facts about the product did "
            "not change; the policy applied to them did."
        )

    substitution = receipt.get("substitution")
    if substitution:
        parts.append(f"A replacement is available: {substitution['replacement_name']}.")

    action = receipt.get("selected_action", "halt")
    parts.append(
        f"The agent is permitted to {action.replace('_', ' ')}, and nothing beyond that."
    )
    return " ".join(part for part in parts if part)


def _configured_adapter():
    """A live adapter, or None. Import failures are swallowed on purpose: a
    missing framework falls back to the summary rather than breaking."""
    try:
        from ramify.agent.langgraph_adapter import LangGraphAdapter
    except Exception:
        return None

    adapter = LangGraphAdapter()
    return adapter if adapter.available() else None


_APPROVING = re.compile(
    r"\b(safe to (buy|purchase|use)|go ahead|(you|agent) (can|may) (buy|purchase|proceed)|"
    r"proceed with (the |this )?purchase|approved (for|to) (buy|purchase)|ok(ay)? to (buy|purchase)|"
    r"fine to (buy|purchase)|recommend(ed)? (buying|purchasing))\b",
    re.IGNORECASE,
)
_STOPPING = re.compile(
    r"\b(recalled|under (an active )?recall|do not (buy|purchase)|must not (buy|purchase|proceed)|"
    r"unsafe|blocked|rejected)\b",
    re.IGNORECASE,
)


def contradicts_decision(text: str, receipt: dict) -> bool:
    """Whether generated prose says the opposite of the signed decision.

    The receipt could not be changed by the model, but its prose was shown
    whatever it said, so text approving a recalled product was accepted as the
    explanation of a blocked receipt (David's L2). Deliberately blunt: a false
    alarm only swaps in the deterministic summary, which is always correct.
    """
    decision = receipt.get("actor_decision", receipt.get("objective_posture", "escalate"))
    if decision in ("block", "hold", "escalate"):
        return bool(_APPROVING.search(text))
    if decision in ("allow", "allow_with_warning"):
        return bool(_STOPPING.search(text))
    return True


def explain_receipt(receipt: dict) -> dict:
    """Explain a receipt without being able to change it."""
    read_only = copy.deepcopy(receipt)

    adapter = _configured_adapter()
    if adapter is not None:
        try:
            text = adapter.explain(read_only)
            if isinstance(text, str) and text.strip():
                if contradicts_decision(text, read_only):
                    return {
                        "text": deterministic_summary(read_only),
                        "source": "deterministic_summary (model text rejected: it contradicted the signed decision)",
                    }
                return {"text": text.strip(), "source": adapter.name}
        except Exception:
            # A model that errors, times out or returns nonsense must not take
            # the demonstration with it.
            pass

    return {"text": deterministic_summary(read_only), "source": "deterministic_summary"}
