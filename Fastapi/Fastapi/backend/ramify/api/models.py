"""Typed request shapes. A malformed agent output is rejected at the edge
rather than reaching the trust logic."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class APIModel(BaseModel):
    """Strict API boundary: reject unknown fields before they reach domain logic."""

    model_config = ConfigDict(extra="forbid")


class IdentifyRequest(APIModel):
    identifier: str = Field(min_length=1, max_length=240)




class InterpretRequest(APIModel):
    """Plain-English request interpretation. The result may select a known
    catalogue identifier but never carries a trust verdict."""

    request_text: str = Field(min_length=1, max_length=1000)
    actor_ref: str = Field(default="consumer_v1", min_length=1, max_length=120)
    mode: str = Field(default="auto", pattern="^(auto|deterministic|local_llm)$")
    # A page that already knows which product card the user selected can narrow
    # the model's catalogue view to that product. This prevents generated text
    # from silently switching the user's explicit selection.
    candidate_refs: list[str] | None = Field(default=None, max_length=12)

class SubjectRequest(APIModel):
    subject_ref: str = Field(min_length=1, max_length=240)


class VerifyRequest(APIModel):
    subject_ref: str = Field(min_length=1, max_length=240)
    policy_ref: str | None = Field(default=None, max_length=240)


class AssessRequest(APIModel):
    identifier: str = Field(min_length=1, max_length=240)
    actor_ref: str = Field(default="consumer_v1", min_length=1, max_length=120)
    policy_ref: str | None = Field(default=None, max_length=240)
    quantity: StrictInt = Field(default=1, ge=1, le=1000)
    # Only an explicit purchase journey should create something for Needs me.
    # Guided demos, tours and other exploratory checks remain auditable receipts
    # but are kept out of the human-authorisation work queue.
    context: str = Field(
        default="purchase",
        pattern="^(purchase|guided_demo|interactive_tour|agent_tool|suggestion|comparison|decision)$",
    )


class CompareRequest(APIModel):
    """One product, selected personas (or all current profiles).

    They do not confer — each independently consumes the same objective
    assessment. Guided experiences can explicitly request the five shipped
    personas so user-created agents do not change the scripted story.
    """

    identifier: str = Field(min_length=1, max_length=240)
    quantity: StrictInt = Field(default=1, ge=1, le=1000)
    actor_refs: list[str] | None = Field(default=None, min_length=1, max_length=20)


class AddToCartRequest(APIModel):
    """The receipt is the permission slip. The server re-reads the sealed copy
    rather than taking the browser's word for what was permitted."""

    receipt_ref: str = Field(min_length=1, max_length=240)


class AgentProfileRequest(APIModel):
    """What a customer may change. Narrowing rules and permitted actions are
    absent on purpose — they are derived from these, so no edit can produce an
    agent more permissive than the assessment allows."""

    label: str = Field(min_length=1, max_length=60)
    summary: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=600)
    autonomy_level: str = Field(default="none", pattern="^(none|clean_only|clean_or_warned)$")
    purchase_style: str = Field(default="cart", pattern="^(cart|requisition)$")
    budget_limit_cents: StrictInt | None = Field(default=None, ge=0, le=100_000_000)
    brand_allowlist: list[str] | None = Field(default=None, max_length=50)
    approved_vendors: list[str] | None = Field(default=None, max_length=50)
    warned_outcome_requires_review: bool = False


class ExplainRequest(APIModel):
    """A receipt for the model to describe. It is never returned modified."""

    receipt: dict[str, Any]


class ReviewRequest(APIModel):
    """A person's decision. The original is never rewritten — a linked
    superseding receipt is appended. Reviewer identity is recorded as a
    demonstration attestation; it is not represented as a personal digital
    signature."""

    receipt_id: str = Field(min_length=1, max_length=240)
    outcome: str = Field(pattern="^(confirmed|overridden)$")
    reviewer_name: str = Field(default="Demo reviewer", min_length=1, max_length=80)
    reviewer_role: str = Field(default="Customer / approver", min_length=1, max_length=80)
    reviewer_note: str = Field(default="", max_length=600)


class AlternativesRequest(APIModel):
    """What else this agent could buy instead."""

    identifier: str = Field(min_length=1, max_length=240)
    actor_ref: str = Field(default="consumer_v1", min_length=1, max_length=120)
    quantity: StrictInt = Field(default=1, ge=1, le=1000)


class ActionEventRequest(APIModel):
    """An Action Gate click. The receipt is what authorises it."""

    receipt_ref: str = Field(min_length=1, max_length=240)
    action: str = Field(min_length=1, max_length=60)
