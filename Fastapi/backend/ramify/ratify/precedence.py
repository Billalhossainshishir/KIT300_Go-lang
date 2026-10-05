"""Posture precedence. Six rules, five postures (v0.4.1 item 4).

Two separate questions, answered separately (client direction, 5 August 2026):

    the posture          the *most restrictive* rule that matched
    the primary reason   the *highest-precedence* rule that matched

Ordering alone would let a first match suppress a more serious condition
further down the list. Taking the most restrictive rule means nothing found is
ever discarded, while the ordering still decides which reason a person is shown
first — a batch under advisory that also carries expired evidence reads as an
advisory, and both reasons are recorded.
"""

from dataclasses import dataclass

from ramify.ratify.checks import (
    FAIL,
    HARD_STOP,
    INCOMPLETE,
    PASS,
    REVIEW,
    CheckResult,
)

ALLOW = "allow"
ALLOW_WITH_WARNING = "allow_with_warning"
HOLD = "hold"
ESCALATE = "escalate"
BLOCK = "block"

# How much each posture restricts an agent. The actor stage may raise this rank
# but never lower it. `escalate` outranks `hold` because an incomplete
# assessment permits strictly fewer automated actions than a known advisory.
RESTRICTIVENESS = {
    ALLOW: 0,
    ALLOW_WITH_WARNING: 1,
    HOLD: 2,
    ESCALATE: 3,
    BLOCK: 4,
}


@dataclass
class PrecedenceOutcome:
    posture: str
    matched_rule: int
    primary_rule: int
    primary_condition: str
    matched_conditions: list[dict]
    reason_codes: list[str]

    def as_dict(self) -> dict:
        return {
            "posture": self.posture,
            "matched_rule": self.matched_rule,
            "primary_rule": self.primary_rule,
            "primary_condition": self.primary_condition,
            "matched_conditions": list(self.matched_conditions),
            "reason_codes": list(self.reason_codes),
        }


def _collect_reason_codes(checks: list[CheckResult]) -> list[str]:
    codes: list[str] = []
    for check in checks:
        for code in check.reason_codes:
            if code not in codes:
                codes.append(code)
    return codes


def _check_set_problems(checks: list[CheckResult], expected: tuple[str, ...] | None) -> list[str]:
    from ramify.ratify.checks import KNOWN_OUTCOMES

    problems = []
    if not checks:
        problems.append("no checks were supplied")
    unknown = sorted({str(c.outcome) for c in checks if c.outcome not in KNOWN_OUTCOMES})
    if unknown:
        problems.append("unknown outcome(s): " + ", ".join(unknown))
    if expected is not None:
        supplied = [c.check_id for c in checks]
        missing = [cid for cid in expected if cid not in supplied]
        repeated = sorted({cid for cid in supplied if supplied.count(cid) > 1})
        if missing:
            problems.append("missing check(s): " + ", ".join(missing))
        if repeated:
            problems.append("repeated check(s): " + ", ".join(repeated))
    return problems


def evaluate(
    checks: list[CheckResult], standing: str, expected: tuple[str, ...] | None = None
) -> PrecedenceOutcome:
    # An empty list, or one whose outcomes fall outside the vocabulary, used to
    # match none of the failure buckets and fall through to allow when standing
    # was clean (David's E4). A check set that cannot be read is a fault in the
    # engine, not a finding about the product, and it must never be approvable,
    # so it blocks rather than escalating to a person.
    problems = _check_set_problems(checks, expected)
    if problems:
        condition = "the check set is incomplete or malformed: " + "; ".join(problems)
        return PrecedenceOutcome(
            posture=BLOCK,
            matched_rule=0,
            primary_rule=0,
            primary_condition=condition,
            matched_conditions=[{
                "rule": 0, "condition": condition, "posture": BLOCK,
                "is_primary_reason": True, "determined_posture": True,
            }],
            reason_codes=["check_set_invalid"],
        )

    by_outcome = {
        FAIL: [c for c in checks if c.outcome == FAIL],
        REVIEW: [c for c in checks if c.outcome == REVIEW],
        INCOMPLETE: [c for c in checks if c.outcome == INCOMPLETE],
        PASS: [c for c in checks if c.outcome == PASS],
    }
    hard_stop_failures = [c for c in by_outcome[FAIL] if c.severity == HARD_STOP]
    standing_clean = standing == "no_active_recall"

    conditions = [
        (
            1,
            "standing is recalled",
            BLOCK,
            standing == "recalled",
        ),
        (
            2,
            "a check failed with hard_stop severity",
            BLOCK,
            bool(hard_stop_failures),
        ),
        (
            3,
            "standing is advisory",
            HOLD,
            standing == "advisory",
        ),
        (
            4,
            "a check needs review, none failed or is incomplete, standing clean",
            ALLOW_WITH_WARNING,
            bool(by_outcome[REVIEW])
            and not by_outcome[FAIL]
            and not by_outcome[INCOMPLETE]
            and standing_clean,
        ),
        (
            5,
            "every check passed and standing is clean",
            ALLOW,
            not by_outcome[FAIL]
            and not by_outcome[REVIEW]
            and not by_outcome[INCOMPLETE]
            and standing_clean,
        ),
        (
            6,
            "evidence or claims are incomplete",
            ESCALATE,
            bool(by_outcome[INCOMPLETE]),
        ),
    ]

    matched = [
        {"rule": order, "condition": description, "posture": posture}
        for order, description, posture, is_met in conditions
        if is_met
    ]

    if not matched:
        # Unreachable, but defaulting to `escalate` means an unforeseen
        # combination asks for a person rather than quietly approving.
        matched = [
            {
                "rule": 6,
                "condition": "no rule matched; defaulted to escalate",
                "posture": ESCALATE,
            }
        ]

    primary = matched[0]
    strictest = max(matched, key=lambda m: RESTRICTIVENESS[m["posture"]])

    for entry in matched:
        entry["is_primary_reason"] = entry["rule"] == primary["rule"]
        entry["determined_posture"] = entry["rule"] == strictest["rule"]

    return PrecedenceOutcome(
        posture=strictest["posture"],
        matched_rule=strictest["rule"],
        primary_rule=primary["rule"],
        primary_condition=primary["condition"],
        matched_conditions=matched,
        reason_codes=_collect_reason_codes(checks),
    )


def is_narrowing(from_posture: str, to_posture: str) -> bool:
    return RESTRICTIVENESS[to_posture] >= RESTRICTIVENESS[from_posture]
