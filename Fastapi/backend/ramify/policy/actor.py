"""Actor policy — component 4. Client direction, 22 July 2026, item 7.

A separate stage over a finished objective posture. The product-trust facts
stay constant; different actors legitimately reach different decisions because
their authority, risk tolerance and permitted actions differ.

Several personas run here but none of them confer — the trust result stays
deterministic and single-sourced, so each consumes the same objective posture
and applies only its own constraints.

Constraints come in two kinds and the receipt records which. A `commercial` one
— budget, brand, approved vendors — is never a safety judgement and must not
read as one. A brand being off a buyer's list says nothing about the product.

The stage may only narrow, and that is enforced rather than trusted.
"""

from dataclasses import dataclass, field

from ramify.data import seed
from ramify.policy import profiles
from ramify.ratify.precedence import RESTRICTIVENESS, is_narrowing

TRUST_DERIVED = "trust_derived"
COMMERCIAL = "commercial"

RULE_KINDS = {
    "warned_outcome_requires_review": TRUST_DERIVED,
    "warned_outcome_requires_a_person": TRUST_DERIVED,
    "autonomy_withheld_on_warned_outcome": TRUST_DERIVED,
    "seller_not_on_approved_vendor_list": COMMERCIAL,
    "over_budget": COMMERCIAL,
    "price_unavailable_for_budget": COMMERCIAL,
    "brand_not_on_allowlist": COMMERCIAL,
}


class PolicyWouldWiden(Exception):
    """Raised when an actor profile tries to make an outcome more permissive."""


@dataclass
class ActorDecision:
    actor_ref: str
    actor_label: str
    objective_posture: str
    decision: str
    narrowed: bool
    applied_rules: list[dict] = field(default_factory=list)
    conditions_evaluated: list[dict] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "actor_ref": self.actor_ref,
            "actor_label": self.actor_label,
            "objective_posture": self.objective_posture,
            "decision": self.decision,
            "narrowed": self.narrowed,
            "applied_rules": list(self.applied_rules),
            "conditions_evaluated": list(self.conditions_evaluated),
            "reason_codes": list(self.reason_codes),
        }


def line_total_cents(subject_ref: str, quantity: int) -> int | None:
    unit = seed.price_cents(subject_ref)
    return None if unit is None else unit * quantity


def _money(cents: int) -> str:
    return f"A${cents / 100:,.2f}"


def _evaluate_conditions(
    profile: dict, objective_posture: str, subject: dict | None, order: dict
) -> list[dict]:
    """Every condition this persona holds, met or not.

    Satisfied ones are reported alongside the rest: an agent that shows only
    its objections reads as an obstacle, one that shows its whole rule set
    reads as a policy.
    """
    conditions: list[dict] = []

    if profile.get("budget_limit_cents") is not None:
        limit = profile["budget_limit_cents"]
        total = order.get("line_total_cents")
        if total is None:
            conditions.append(
                {
                    "id": "price_unavailable_for_budget",
                    "kind": COMMERCIAL,
                    "label": f"Spend ceiling {_money(limit)} per line",
                    "detail": "This listing carries no price, so the spend ceiling requires review.",
                    "met": False,
                }
            )
        else:
            within = total <= limit
            conditions.append(
                {
                    "id": "over_budget",
                    "kind": COMMERCIAL,
                    "label": f"Spend ceiling {_money(limit)} per line",
                    "detail": (
                        f"Line total {_money(total)}"
                        f"{' is within the ceiling.' if within else ' is over the ceiling.'}"
                    ),
                    "met": within,
                }
            )

    if profile.get("brand_allowlist"):
        brand = (subject or {}).get("brand")
        permitted = brand in profile["brand_allowlist"]
        conditions.append(
            {
                "id": "brand_not_on_allowlist",
                "kind": COMMERCIAL,
                "label": "Brand arrangement",
                "detail": (
                    f"{brand} is covered by the arrangement."
                    if permitted
                    else f"{brand} is outside the arrangement. This is a commercial "
                    "restriction, not a finding about the product."
                ),
                "met": permitted,
            }
        )

    if profile.get("approved_vendors"):
        seller_ref = (subject or {}).get("seller_ref")
        approved = seller_ref in profile["approved_vendors"]
        seller = seed.seller(seller_ref or "")
        name = seller["name"] if seller else "the seller"
        conditions.append(
            {
                "id": "seller_not_on_approved_vendor_list",
                "kind": COMMERCIAL,
                "label": "Approved vendor list",
                "detail": (
                    f"{name} is on the approved vendor list."
                    if approved
                    else f"{name} is not on the approved vendor list. The seller is "
                    "genuine; the arrangement to buy from them is what is missing."
                ),
                "met": approved,
            }
        )

    if any(r["id"] == "warned_outcome_requires_review" for r in profile.get("narrowing_rules", [])):
        warned = objective_posture == "allow_with_warning"
        conditions.append(
            {
                "id": "warned_outcome_requires_review",
                "kind": TRUST_DERIVED,
                "label": "Warned outcomes need a person",
                "detail": (
                    "The assessment carried a warning, so this cannot proceed unattended."
                    if warned
                    else "The assessment carried no warning."
                ),
                "met": not warned,
            }
        )

    return conditions


def _rule_applies(
    rule: dict, objective_posture: str, profile: dict, subject: dict | None, order: dict
) -> bool:
    rule_id = rule["id"]

    if rule_id == "warned_outcome_requires_review":
        return objective_posture == "allow_with_warning"

    if rule_id == "seller_not_on_approved_vendor_list":
        approved = profile.get("approved_vendors", [])
        return bool(approved) and (subject or {}).get("seller_ref") not in approved

    if rule_id == "price_unavailable_for_budget":
        return profile.get("budget_limit_cents") is not None and order.get("line_total_cents") is None

    if rule_id == "over_budget":
        limit = profile.get("budget_limit_cents")
        total = order.get("line_total_cents")
        return limit is not None and total is not None and total > limit

    if rule_id == "brand_not_on_allowlist":
        allowlist = profile.get("brand_allowlist", [])
        return bool(allowlist) and (subject or {}).get("brand") not in allowlist

    return False


def apply(
    objective_posture: str,
    actor_ref: str,
    subject: dict | None,
    order: dict | None = None,
) -> ActorDecision:
    """Narrow an objective posture according to one persona's policy."""
    profile = profiles.profile(actor_ref)
    if profile is None:
        raise KeyError(f"unknown actor profile: {actor_ref}")

    order = order or {}
    decision = objective_posture
    applied: list[dict] = []
    reason_codes: list[str] = []

    for rule in profile.get("narrowing_rules", []):
        if not _rule_applies(rule, objective_posture, profile, subject, order):
            continue
        candidate = rule["narrow_to"]
        # A rule that would loosen the outcome is ignored, not obeyed — an
        # advisory hold cannot be talked back down by a tolerant persona.
        if RESTRICTIVENESS[candidate] <= RESTRICTIVENESS[decision]:
            continue
        decision = candidate
        applied.append(
            {
                "rule_id": rule["id"],
                "kind": RULE_KINDS.get(rule["id"], COMMERCIAL),
                "narrowed_to": candidate,
                "reason_code": rule.get("reason_code", ""),
            }
        )
        if rule.get("reason_code") and rule["reason_code"] not in reason_codes:
            reason_codes.append(rule["reason_code"])

    if not is_narrowing(objective_posture, decision):
        raise PolicyWouldWiden(
            f"profile {actor_ref} produced {decision} from an objective "
            f"{objective_posture}, which is less restrictive"
        )

    return ActorDecision(
        actor_ref=actor_ref,
        actor_label=profile["label"],
        objective_posture=objective_posture,
        decision=decision,
        narrowed=decision != objective_posture,
        applied_rules=applied,
        conditions_evaluated=_evaluate_conditions(profile, objective_posture, subject, order),
        reason_codes=reason_codes,
    )


def permitted_actions(actor_ref: str, decision: str) -> list[str]:
    profile = profiles.profile(actor_ref)
    if profile is None:
        return ["halt"]
    return list(profile["permitted_actions"].get(decision, ["halt"]))


def will_purchase_unattended(actor_ref: str, decision: str) -> bool:
    """Whether this persona buys with no person involved.

    Autonomy changes which permitted action is taken, never the posture, so it
    cannot make an outcome more permissive than the assessment allowed.
    """
    profile = profiles.profile(actor_ref)
    if profile is None or profile.get("purchase_style", "cart") != "cart":
        return False
    return decision in profile.get("auto_purchase_on", [])
