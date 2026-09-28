"""The posture vocabulary, its user-facing mapping, and the transition matrix.

Client direction, 5 August 2026: the signed specification's vocabulary is used
internally and in the machine-readable receipt, with clearer wording as a
presentation mapping — and the two must not circulate without a versioned
mapping table. This is that table.

It also publishes the objective-to-actor transition matrix, so the claim that
actor policy may only narrow is testable rather than interpretive.
"""

from ramify.ratify.precedence import RESTRICTIVENESS

MAPPING_VERSION = "posture_mapping_v1.0.0"

# Machine posture → what a person is told. The machine value is what travels in
# the receipt; the rest of this row never does.
POSTURE_MAPPING = {
    "allow": {
        "machine_posture": "allow",
        "user_facing": "Approved",
        "meaning": "Every check passed. The agent may proceed.",
        "light": "green",
        "carries_warning": False,
        "needs_a_person": False,
    },
    "allow_with_warning": {
        "machine_posture": "allow_with_warning",
        "user_facing": "Approved with warning",
        "meaning": "The agent may proceed, but there is a finding the buyer should see first.",
        "light": "orange",
        "carries_warning": True,
        "needs_a_person": False,
    },
    "hold": {
        "machine_posture": "hold",
        "user_facing": "Human review required",
        "meaning": "The agent stops and a person decides.",
        "light": "orange",
        "carries_warning": False,
        "needs_a_person": True,
    },
    "escalate": {
        "machine_posture": "escalate",
        "user_facing": "Human review required",
        "meaning": "Not enough was on file to judge. The agent stops and a person decides.",
        "light": "orange",
        "carries_warning": False,
        "needs_a_person": True,
    },
    "block": {
        "machine_posture": "block",
        "user_facing": "Rejected",
        "meaning": "A check failed on grounds no policy can soften. The agent must not proceed.",
        "light": "red",
        "carries_warning": False,
        "needs_a_person": False,
    },
}

# Standing is a separate vocabulary from posture and maps to its own colour.
# An advisory is amber and a recall is red; a voluntary recall is still a recall
# and is never stored as an advisory.
STANDING_MAPPING = {
    "no_active_recall": {"user_facing": "No recall or advisory", "light": "green"},
    "advisory": {"user_facing": "Under advisory", "light": "amber"},
    "recalled": {"user_facing": "Recalled", "light": "red"},
    "unknown": {"user_facing": "No standing record held", "light": "amber"},
}

ORDER = sorted(RESTRICTIVENESS, key=RESTRICTIVENESS.get)


def transition_matrix() -> dict:
    """Every objective-to-actor transition, and whether it is permitted.

    A transition is permitted when the actor decision is at least as
    restrictive as the objective posture. Publishing the whole matrix makes the
    monotonicity claim checkable rather than something to be taken on trust.
    """
    rows = []
    for objective in ORDER:
        for actor in ORDER:
            rows.append(
                {
                    "objective_posture": objective,
                    "actor_decision": actor,
                    "objective_rank": RESTRICTIVENESS[objective],
                    "actor_rank": RESTRICTIVENESS[actor],
                    "permitted": RESTRICTIVENESS[actor] >= RESTRICTIVENESS[objective],
                    "kind": (
                        "unchanged"
                        if actor == objective
                        else "narrows"
                        if RESTRICTIVENESS[actor] > RESTRICTIVENESS[objective]
                        else "widens"
                    ),
                }
            )
    return {
        "mapping_version": MAPPING_VERSION,
        "order_least_to_most_restrictive": ORDER,
        "rows": rows,
        "note": (
            "An actor decision is permitted only where it is at least as restrictive as "
            "the objective posture. Every row marked 'widens' is rejected by the policy "
            "stage rather than accepted."
        ),
    }


def describe(posture: str) -> dict:
    return POSTURE_MAPPING.get(posture, POSTURE_MAPPING["escalate"])


def describe_standing(standing: str) -> dict:
    return STANDING_MAPPING.get(standing, STANDING_MAPPING["unknown"])
