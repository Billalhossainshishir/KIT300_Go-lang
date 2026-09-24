"""Agent profiles, including the ones a customer edits.

A buyer can change the spend ceiling, the brands, the sellers and whether the
agent may buy unattended. What they cannot do — by construction, not by
validation — is build an agent more permissive than the assessment allows.

The safety comes from what is editable. A profile is a set of inputs; the
narrowing rules and permitted actions are *derived* from them. Nobody can
hand-write a rule that loosens an outcome because rules are not hand-written,
and a recalled product permits `halt` whatever anyone types into the editor.

Edits live in the local data store; the embedded seed is never written to.
"""

import copy
from pathlib import Path
from threading import RLock

from ramify.crypto import keys
from ramify.data import seed
from ramify.storage import read_json, write_json_atomic

CUSTOM_PROFILES_NAME = "agent_profiles.json"
_PROFILE_LOCK = RLock()

# Autonomy a buyer may grant. `block`, `hold` and `escalate` are absent on
# purpose and there is no way to add them: an agent cannot be configured to buy
# something the assessment stopped.
AUTONOMY_LEVELS = {
    "none": [],
    "clean_only": ["allow"],
    "clean_or_warned": ["allow", "allow_with_warning"],
}

AUTONOMY_LABELS = {
    "none": "Never buys without a person",
    "clean_only": "Buys unattended when every check passes",
    "clean_or_warned": "Buys unattended even when a warning is attached",
}

PURCHASE_STYLES = {
    "cart": "add_to_mock_cart",
    "requisition": "create_mock_requisition",
}

EDITABLE_FIELDS = (
    "label",
    "summary",
    "description",
    "autonomy_level",
    "purchase_style",
    "budget_limit_cents",
    "brand_allowlist",
    "approved_vendors",
    "warned_outcome_requires_review",
)


class InvalidProfile(ValueError):
    """Raised when an edit could not produce a coherent agent."""


def _store_path() -> Path:
    store = keys.local_data_store()
    store.mkdir(parents=True, exist_ok=True)
    return store / CUSTOM_PROFILES_NAME


def _load_custom() -> dict:
    with _PROFILE_LOCK:
        value = read_json(_store_path(), dict)
        if not isinstance(value, dict):
            raise InvalidProfile("The local agent profile store is not a JSON object.")
        return value


def _save_custom(profile_data: dict) -> None:
    with _PROFILE_LOCK:
        write_json_atomic(_store_path(), profile_data)


def _derive_narrowing_rules(profile: dict) -> list[dict]:
    """The rule list, built from the profile's inputs.

    Every rule narrows. A caller controls whether a rule exists, never what it
    does, so there is no path by which one could widen.
    """
    rules = []
    autonomy = (
        AUTONOMY_LEVELS.get(profile.get("autonomy_level", "none"), [])
        if profile.get("purchase_style", "cart") == "cart"
        else []
    )

    # One rule, two ways of saying why: an agent that could otherwise have
    # bought this is withholding autonomy, one that never buys unattended is
    # just routing a warning. Only the first is a capability being held back.
    if profile.get("warned_outcome_requires_review"):
        rules.append(
            {
                "id": "warned_outcome_requires_review",
                "when": "objective_posture == allow_with_warning",
                "narrow_to": "hold",
                "reason_code": (
                    "autonomy_withheld_on_warned_outcome"
                    if autonomy
                    else "warned_outcome_requires_a_person"
                ),
            }
        )
    if profile.get("budget_limit_cents") is not None:
        # A spend ceiling cannot safely be applied when the listing has no
        # price. Treat unknown price as a review condition rather than silently
        # behaving as though the ceiling passed.
        rules.append(
            {
                "id": "price_unavailable_for_budget",
                "when": "line total is unavailable",
                "narrow_to": "hold",
                "reason_code": "line_total_unavailable_for_agent_budget",
            }
        )
        rules.append(
            {
                "id": "over_budget",
                "when": "line total > budget_limit_cents",
                "narrow_to": "hold",
                "reason_code": "line_total_exceeds_agent_budget",
            }
        )
    if profile.get("brand_allowlist"):
        rules.append(
            {
                "id": "brand_not_on_allowlist",
                "when": "brand not in brand_allowlist",
                "narrow_to": "hold",
                "reason_code": "brand_outside_agent_arrangement",
            }
        )
    if profile.get("approved_vendors"):
        rules.append(
            {
                "id": "seller_not_on_approved_vendor_list",
                "when": "seller not in approved_vendors",
                "narrow_to": "hold",
                "reason_code": "seller_not_on_approved_vendor_list",
            }
        )

    # An agent that buys unattended on a clean result must still stop on a
    # warned one unless the buyer has explicitly said otherwise. Without this,
    # granting autonomy would quietly also grant tolerance of warnings.
    if autonomy == ["allow"] and not profile.get("warned_outcome_requires_review"):
        rules.append(
            {
                "id": "warned_outcome_requires_review",
                "when": "objective_posture == allow_with_warning",
                "narrow_to": "hold",
                "reason_code": "autonomy_withheld_on_warned_outcome",
            }
        )

    return rules


def _derive_permitted_actions(profile: dict) -> dict[str, list[str]]:
    """Derive safe actions from the profile inputs.

    `purchase_autonomously` is a consumer-checkout action. A procurement
    profile stages a requisition instead; it must never accidentally acquire a
    consumer basket path just because an autonomy setting was supplied.
    """
    style = profile.get("purchase_style", "cart")
    primary = PURCHASE_STYLES.get(style, "add_to_mock_cart")
    autonomy = AUTONOMY_LEVELS.get(profile.get("autonomy_level", "none"), []) if style == "cart" else []

    def buying(decision: str) -> list[str]:
        actions = ["purchase_autonomously"] if decision in autonomy else []
        return actions + [primary, "compare_alternatives"]

    return {
        "allow": buying("allow"),
        "allow_with_warning": buying("allow_with_warning"),
        # Nothing below this line can buy anything, whatever the profile says.
        "hold": ["create_review_task", "compare_alternatives", "halt"],
        "escalate": ["create_review_task", "halt"],
        "block": ["halt"],
    }


def describe(profile: dict) -> str:
    """A one-line summary derived from the settings, not stored alongside them.

    A card still reading "ceiling of A$30" after the ceiling moved to A$80 is
    worse than no summary — a reader cannot tell which of the two to believe.
    """
    parts = []
    style = profile.get("purchase_style", "cart")
    autonomy = profile.get("autonomy_level", "none")
    if style == "requisition":
        parts.append("stages procurement requisitions")
    elif autonomy == "clean_or_warned":
        parts.append("buys unattended, warnings and all")
    elif autonomy == "clean_only":
        parts.append("buys unattended on a clean result")
    else:
        parts.append("always asks first")

    if profile.get("budget_limit_cents") is not None:
        parts.append(f"up to {_money(profile['budget_limit_cents'])} a line")
    brands = profile.get("brand_allowlist") or []
    if brands:
        parts.append(f"{len(brands)} brand{'s' if len(brands) > 1 else ''} only")
    vendors = profile.get("approved_vendors") or []
    if vendors:
        parts.append(f"{len(vendors)} approved seller{'s' if len(vendors) > 1 else ''}")

    summary = ", ".join(parts)
    return summary[0].upper() + summary[1:]


def _money(cents: int) -> str:
    return f"A${cents / 100:,.2f}".replace(".00", "")


def _compile(profile: dict) -> dict:
    compiled = dict(profile)
    compiled["derived_summary"] = describe(profile)
    if not compiled.get("summary"):
        compiled["summary"] = compiled["derived_summary"]
    cart_style = profile.get("purchase_style", "cart") == "cart"
    compiled["autonomy"] = (
        "purchases_unattended"
        if cart_style and AUTONOMY_LEVELS.get(profile.get("autonomy_level", "none"))
        else "assists"
    )
    compiled["auto_purchase_on"] = (
        AUTONOMY_LEVELS.get(profile.get("autonomy_level", "none"), []) if cart_style else []
    )
    compiled["narrowing_rules"] = _derive_narrowing_rules(profile)
    compiled["permitted_actions"] = _derive_permitted_actions(profile)
    return compiled


def _seed_profiles() -> dict:
    """The shipped profiles, expressed as editable inputs."""
    profiles = {}
    for ref, record in seed.actor_profiles().items():
        auto = record.get("auto_purchase_on", [])
        level = next(
            (name for name, value in AUTONOMY_LEVELS.items() if value == auto),
            "none",
        )
        profiles[ref] = {
            "ref": ref,
            "label": record["label"],
            "summary": record["summary"],
            "description": record["description"],
            "autonomy_level": level,
            "purchase_style": (
                "requisition"
                if "create_mock_requisition" in record["permitted_actions"].get("allow", [])
                else "cart"
            ),
            "budget_limit_cents": record.get("budget_limit_cents"),
            "brand_allowlist": record.get("brand_allowlist"),
            "approved_vendors": record.get("approved_vendors"),
            "warned_outcome_requires_review": any(
                r["id"] == "warned_outcome_requires_review"
                for r in record.get("narrowing_rules", [])
            ),
            "built_in": True,
            "edited": False,
        }
    return profiles


def all_profiles() -> dict:
    """Shipped profiles with any customer edits laid over the top."""
    profiles = _seed_profiles()
    for ref, custom in _load_custom().items():
        if not isinstance(custom, dict):
            raise InvalidProfile(f"Persisted profile {ref!r} is not a JSON object.")
        # Re-validate persisted mutable inputs every time they cross the storage
        # boundary. A manually edited/corrupt local JSON file therefore fails
        # closed instead of compiling unchecked policy settings.
        validated = _validate(custom)
        base = profiles.get(ref, {"ref": ref, "built_in": False})
        merged = {**base, **validated, "ref": ref}
        merged["built_in"] = base.get("built_in", False)
        merged["edited"] = True
        profiles[ref] = merged
    return {ref: _compile(profile) for ref, profile in profiles.items()}


def profile(ref: str) -> dict | None:
    return all_profiles().get(ref)


def _validate(fields: dict) -> dict:
    clean: dict = {}

    label = str(fields.get("label", "")).strip()
    if not label:
        raise InvalidProfile("An agent needs a name.")
    if len(label) > 60:
        raise InvalidProfile("Keep the name under 60 characters.")
    clean["label"] = label

    clean["summary"] = str(fields.get("summary", "")).strip()[:120]
    clean["description"] = str(fields.get("description", "")).strip()[:600]

    level = fields.get("autonomy_level", "none")
    if level not in AUTONOMY_LEVELS:
        raise InvalidProfile(f"Unknown autonomy setting: {level}")
    clean["autonomy_level"] = level

    style = fields.get("purchase_style", "cart")
    if style not in PURCHASE_STYLES:
        raise InvalidProfile(f"Unknown purchase style: {style}")
    clean["purchase_style"] = style
    # Autonomy means unattended consumer checkout. A requisition is a staged
    # procurement record, so retaining an autonomy value would describe a
    # capability that cannot and should not exist in this workflow.
    if style == "requisition":
        clean["autonomy_level"] = "none"

    budget = fields.get("budget_limit_cents")
    if budget is None:
        clean["budget_limit_cents"] = None
    else:
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise InvalidProfile("The spend ceiling must be a whole number of cents, not a coerced value.")
        if budget < 0 or budget > 100_000_000:
            raise InvalidProfile("A spend ceiling must be between 0 and 100000000 cents.")
        clean["budget_limit_cents"] = budget

    brands = fields.get("brand_allowlist") or None
    if brands is not None:
        if not isinstance(brands, list):
            raise InvalidProfile("The brand arrangement must be a list.")
        known = {record["brand"] for record in seed.subjects().values()}
        unknown = [b for b in brands if b not in known]
        if unknown:
            raise InvalidProfile(f"Not a brand in this catalogue: {', '.join(unknown)}")
    clean["brand_allowlist"] = brands

    vendors = fields.get("approved_vendors") or None
    if vendors is not None:
        if not isinstance(vendors, list):
            raise InvalidProfile("The approved vendor list must be a list.")
        unknown = [v for v in vendors if seed.seller(v) is None]
        if unknown:
            raise InvalidProfile(f"Not a seller in this catalogue: {', '.join(unknown)}")
    clean["approved_vendors"] = vendors

    clean["warned_outcome_requires_review"] = bool(
        fields.get("warned_outcome_requires_review", False)
    )
    return clean


def save(ref: str, fields: dict) -> dict:
    """Create or edit an agent without risking a lost concurrent update."""
    with _PROFILE_LOCK:
        custom = _load_custom()
        custom[ref] = {**_validate(fields), "ref": ref}
        _save_custom(custom)
    return all_profiles()[ref]


def create(fields: dict) -> dict:
    """Add a new agent, choosing and writing its reference as one operation."""
    label = str(fields.get("label", "")).strip()
    if not label:
        raise InvalidProfile("An agent needs a name.")
    slug = "".join(c if c.isalnum() else "_" for c in label.lower()).strip("_")[:40]
    if not slug:
        raise InvalidProfile("That name has no letters or numbers in it.")

    with _PROFILE_LOCK:
        existing = all_profiles()
        ref = f"custom_{slug}"
        suffix = 2
        while ref in existing:
            ref = f"custom_{slug}_{suffix}"
            suffix += 1
        custom = _load_custom()
        custom[ref] = {**_validate(fields), "ref": ref}
        _save_custom(custom)
    return all_profiles()[ref]


def reset(ref: str) -> dict | None:
    """Undo an edit, or delete an agent the customer added."""
    with _PROFILE_LOCK:
        custom = _load_custom()
        custom.pop(ref, None)
        _save_custom(custom)
    return all_profiles().get(ref)


def reset_all() -> None:
    with _PROFILE_LOCK:
        _save_custom({})


def preview(fields: dict) -> dict:
    """Compile without saving, so the editor can show an edit's effect."""
    return _compile({**_validate(fields), "ref": "preview", "built_in": False, "edited": True})


def as_catalogue_entry(compiled: dict) -> dict:
    entry = copy.deepcopy(compiled)
    entry["autonomy_label"] = AUTONOMY_LABELS[compiled.get("autonomy_level", "none")]
    return entry
