"""The Action Gate — client direction, 22 July 2026, item 6.

What the agent is then permitted to do with the result: one selected action,
drawn from the set its decision allows.

Autonomy lives here rather than in the policy stage, and the placement is the
point. A persona that buys unattended is choosing among actions its decision
already permits, so the posture is untouched and autonomy cannot widen an
outcome.

Every action is simulated. A substitution appears here rather than as a posture
because a replacement is a relationship and a next action, not a verdict.
"""

from ramify.data import seed
from ramify.policy import actor as actor_policy

PREFERRED_BY_DECISION = {
    "allow": ("add_to_mock_cart", "create_mock_requisition"),
    "allow_with_warning": ("add_to_mock_cart", "create_review_task"),
    "hold": ("create_review_task",),
    "escalate": ("create_review_task",),
    "block": ("halt",),
}

DESCRIPTIONS = {
    "purchase_autonomously": "Complete the purchase with no person involved. Simulated.",
    "add_to_mock_cart": "Add to a simulated cart for a person to confirm.",
    "create_mock_requisition": "Raise a simulated purchase requisition.",
    "compare_alternatives": "Offer the buyer a different product.",
    "create_review_task": "Route to a person and pause until they decide.",
    "halt": "Stop. Take no further automated action.",
}

# The two decisions that hand the question to a person. The interface changes
# state on these and the review queue is built from them.
ESCALATING = ("hold", "escalate")


def select(decision: str, actor_ref: str, subject: dict | None) -> dict:
    """Choose one action and record what else was available."""
    permitted = actor_policy.permitted_actions(actor_ref, decision)
    unattended = actor_policy.will_purchase_unattended(actor_ref, decision)

    if unattended and "purchase_autonomously" in permitted:
        selected = "purchase_autonomously"
    else:
        selected = "halt"
        for candidate in PREFERRED_BY_DECISION.get(decision, ()):
            if candidate in permitted:
                selected = candidate
                break
        else:
            if permitted:
                selected = permitted[0]

    result = {
        "decision": decision,
        "selected_action": selected,
        "selected_action_description": DESCRIPTIONS.get(selected, ""),
        "permitted_actions": permitted,
        "unattended": selected == "purchase_autonomously",
        "requires_human": decision in ESCALATING,
        "simulated": True,
    }

    replacement_ref = (subject or {}).get("superseded_by")
    if replacement_ref and "compare_alternatives" in permitted:
        replacement = seed.subject(replacement_ref)
        pack = seed.policy_pack()["supersession"]
        result["substitution"] = {
            "superseded_by": replacement_ref,
            "replacement_name": replacement["name"] if replacement else replacement_ref,
            "note": (subject or {}).get("supersession_note", ""),
            "reason_code": pack["reason_code"],
            "offered_action": pack["offers_action"],
        }

    return result
