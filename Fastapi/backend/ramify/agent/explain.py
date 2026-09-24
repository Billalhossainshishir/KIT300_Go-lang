"""Turning a sealed receipt into plain English.

Two things matter and neither is the prose. The model gets a deep copy, so it
cannot alter what the system decided even by accident. And there is always an
answer: with no model configured a deterministic summary stands in, which keeps
a slow or absent model off the critical path of a demonstration.
"""

import copy

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
}


def deterministic_summary(receipt: dict) -> str:
    """Derived from the receipt alone. No model involved."""
    objective = receipt.get("objective_posture", "escalate")
    decision = receipt.get("actor_decision", objective)
    name = receipt.get("product_name") or receipt.get("subject_ref", "this product")

    parts = [f"{name}. {POSTURE_SENTENCE.get(objective, '')}".strip()]

    reasons = [
        REASON_SENTENCE[code]
        for code in receipt.get("reason_codes", [])
        if code in REASON_SENTENCE
    ]
    if reasons:
        if len(reasons) == 1:
            parts.append(f"The finding was that {reasons[0]}.")
        else:
            listed = "; ".join(reasons[:-1])
            parts.append(f"The findings were that {listed}; and {reasons[-1]}.")

    if receipt.get("actor_narrowed"):
        parts.append(
            f"Assessed for {receipt.get('actor_label', 'this actor')}, the outcome "
            f"tightens from {objective.replace('_', ' ')} to "
            f"{decision.replace('_', ' ')}. The facts about the product did not "
            "change; the policy applied to them did."
        )

    substitution = receipt.get("substitution")
    if substitution:
        parts.append(f"A replacement is available: {substitution['replacement_name']}.")

    action = receipt.get("selected_action", "halt")
    parts.append(
        f"The agent is permitted to {action.replace('_', ' ')}, and nothing beyond that."
    )
    return " ".join(part for part in parts if part)


def _contradicts_receipt(text: str, receipt: dict) -> bool:
    """Conservative guard against prose that reverses the sealed decision."""
    lowered = " ".join(text.casefold().split())
    decision = receipt.get("actor_decision") or receipt.get("objective_posture")
    approval_terms = ("safe to buy", "safe to purchase", "approved to buy", "approved to purchase", "may proceed", "can proceed", "purchase is allowed", "buy this")
    stop_terms = ("must not proceed", "do not purchase", "cannot purchase", "blocked", "must stop")
    if decision in {"block", "hold", "escalate"} and any(term in lowered for term in approval_terms):
        return True
    if decision in {"allow", "allow_with_warning"} and any(term in lowered for term in stop_terms):
        return True
    return False


def _configured_adapter():
    """A live adapter, or None. Import failures are swallowed on purpose: a
    missing framework falls back to the summary rather than breaking."""
    try:
        from ramify.agent.langgraph_adapter import LangGraphAdapter
    except Exception:
        return None

    adapter = LangGraphAdapter()
    return adapter if adapter.available() else None


def explain_receipt(receipt: dict) -> dict:
    """Explain a receipt without being able to change it."""
    read_only = copy.deepcopy(receipt)

    authoritative = deterministic_summary(read_only)
    adapter = _configured_adapter()
    if adapter is not None:
        try:
            text = adapter.explain(read_only)
            if isinstance(text, str) and text.strip():
                candidate = text.strip()
                if not _contradicts_receipt(candidate, read_only):
                    return {
                        "text": candidate,
                        "authoritative_summary": authoritative,
                        "source": adapter.name,
                        "model_text_accepted": True,
                    }
                return {
                    "text": authoritative,
                    "authoritative_summary": authoritative,
                    "source": "deterministic_summary:contradictory_model_rejected",
                    "model_text_accepted": False,
                }
        except Exception:
            pass

    return {
        "text": authoritative,
        "authoritative_summary": authoritative,
        "source": "deterministic_summary",
        "model_text_accepted": False,
    }
