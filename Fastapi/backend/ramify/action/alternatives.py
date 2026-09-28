"""Suggesting something the agent could actually buy.

When an agent stops on a product that the checks found nothing wrong with, the
buyer has been told no for a reason that has nothing to do with the product —
over budget, wrong brand, unapproved seller. Leaving them there is unhelpful,
so this looks for something in the catalogue that clears both the assessment
and that agent's own conditions.

Suggestions are only ever made where the objective assessment was clean or
warned. Nothing is offered as an alternative to a recall.
"""

from ramify.data import seed
from ramify.ratify.precedence import RESTRICTIVENESS

# Offering a substitute for something that failed on safety grounds would read
# as routing around the finding.
SUGGESTIBLE_FROM = ("allow", "allow_with_warning")
MAX_SUGGESTIONS = 3


def _reason_summary(outcome: dict) -> str:
    if outcome["actor_decision"] == "allow":
        return "clears every check and your agent's own conditions"
    if outcome["actor_decision"] == "allow_with_warning":
        return "clears your agent's conditions, with a finding attached"
    return ""


def find(subject_ref: str, actor_ref: str, quantity: int, blocked_outcome: dict) -> dict | None:
    """Products the same agent could buy instead.

    Deliberately runs the whole engine per candidate rather than guessing from
    price alone: a suggestion the agent would also refuse is worse than none.
    """
    if blocked_outcome["objective_posture"] not in SUGGESTIBLE_FROM:
        return None
    if not blocked_outcome["requires_human"]:
        return None

    # Alternatives are a way around a buyer/commercial constraint, never a way
    # around a trust-derived warning. If the stop contains any trust-derived
    # policy rule (for example "warnings need a person"), do not route around it.
    applied = blocked_outcome.get("applied_rules") or []
    if not any(rule.get("kind") == "commercial" for rule in applied):
        return None
    if any(rule.get("kind") != "commercial" for rule in applied):
        return None

    from ramify import engine

    subject = seed.subject(subject_ref)
    if subject is None:
        return None

    unit_price = seed.price_cents(subject_ref)
    candidates = []

    for ref, record in seed.subjects().items():
        if ref == subject_ref or record["category"] != subject["category"]:
            continue

        outcome = engine.assess(
            ref, actor_ref, None, quantity, context="suggestion", persist_receipt=False
        )
        if outcome["requires_human"] or not outcome["can_add_to_cart"]:
            continue

        candidate_price = outcome["order"].get("line_total_cents")
        candidates.append(
            {
                "subject_ref": ref,
                "product_name": outcome["product_name"],
                "brand": record["brand"],
                "line_total_cents": candidate_price,
                "unit_price_cents": seed.price_cents(ref),
                "objective_posture": outcome["objective_posture"],
                "actor_decision": outcome["actor_decision"],
                "why": _reason_summary(outcome),
                "assessment_context": "exploratory",
                "is_named_replacement": record.get("supersedes") == subject_ref
                or subject.get("superseded_by") == ref,
            }
        )

    if not candidates:
        return None

    # A product the manufacturer names as the replacement comes first; after
    # that, the cleanest result, then the closest price.
    candidates.sort(
        key=lambda c: (
            not c["is_named_replacement"],
            RESTRICTIVENESS[c["actor_decision"]],
            abs((c["unit_price_cents"] or 0) - (unit_price or 0)),
        )
    )

    return {
        "because": blocked_outcome["escalation"]["headline"] if blocked_outcome.get("escalation") else "",
        "actor_ref": actor_ref,
        "actor_label": blocked_outcome["actor_label"],
        "candidates": candidates[:MAX_SUGGESTIONS],
        "searched": len(seed.subjects()) - 1,
        "note": (
            "Exploratory only: assessed for the same agent, at the same quantity, against the same checks. "
            "No purchase-authority receipt is persisted for a suggestion; selecting one triggers a fresh assessment."
        ),
    }
