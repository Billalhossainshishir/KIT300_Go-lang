"""RATIFY — component 3. The seven named checks.

Each carries its own rule, evidence requirement and severity (client direction,
22 July 2026), which replaced the two-of-three consensus rule: majority voting
lets two stale certificates outvote one authoritative regulator. Here a recall
fails on its own however much positive evidence sits beside it.

Four outcomes: `pass`, `review`, `fail`, `incomplete`. The last is deliberately
not `fail` — missing evidence is not evidence of a problem, and collapsing the
two would report a product as unsafe when it simply has nothing on file.
"""

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature

from ramify.crypto import keys
from ramify.data import seed
from ramify.ratify.evidence_binding import binding_payload

PASS = "pass"
REVIEW = "review"
FAIL = "fail"
INCOMPLETE = "incomplete"

HARD_STOP = "hard_stop"
INCOMPLETE_SEVERITY = "incomplete"
POLICY_DEPENDENT = "policy_dependent"
INFORMATIONAL = "informational"


@dataclass
class CheckResult:
    check_id: str
    label: str
    outcome: str
    severity: str
    detail: str
    reason_codes: list[str] = field(default_factory=list)
    evidence_consulted: list[str] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "label": self.label,
            "outcome": self.outcome,
            "severity": self.severity,
            "detail": self.detail,
            "reason_codes": list(self.reason_codes),
            "evidence_consulted": list(self.evidence_consulted),
            "findings": list(self.findings),
        }


def _evidence_for(subject: dict) -> list[dict]:
    refs: list[str] = []
    for claim in subject.get("claims", []):
        refs.extend(claim.get("evidence_refs", []))
    records = []
    for ref in dict.fromkeys(refs):
        record = seed.evidence(ref)
        if record is not None:
            records.append(record)
    return records


def check_identity(identify_result: dict) -> CheckResult:
    if identify_result.get("resolved"):
        return CheckResult(
            "identity",
            "Identity resolution",
            PASS,
            INFORMATIONAL,
            f"Identifier resolves to exactly one subject using "
            f"{identify_result.get('match_method', 'an exact identifier match')}.",
        )
    candidates = identify_result.get("candidates") or []
    if candidates:
        return CheckResult(
            "identity",
            "Identity resolution",
            INCOMPLETE,
            INCOMPLETE_SEVERITY,
            f"Identifier matches {len(candidates)} subjects and cannot be narrowed.",
            reason_codes=["identity_ambiguous"],
        )
    return CheckResult(
        "identity",
        "Identity resolution",
        INCOMPLETE,
        INCOMPLETE_SEVERITY,
        "Identifier does not resolve to any known subject.",
        reason_codes=["identity_unresolved"],
    )


def check_standing(status_result: dict) -> CheckResult:
    standing = status_result.get("standing")
    detail = status_result.get("detail") or ""

    if standing == "recalled":
        return CheckResult(
            "standing",
            "Recall and advisory standing",
            FAIL,
            HARD_STOP,
            detail or "An active recall applies.",
            reason_codes=["active_recall_on_batch"],
        )
    if standing == "advisory":
        return CheckResult(
            "standing",
            "Recall and advisory standing",
            REVIEW,
            HARD_STOP,
            detail or "An active advisory applies.",
            reason_codes=["active_advisory_on_batch"],
        )
    if standing == "no_active_recall":
        return CheckResult(
            "standing",
            "Recall and advisory standing",
            PASS,
            INFORMATIONAL,
            "No recall or advisory is recorded against this subject.",
        )
    return CheckResult(
        "standing",
        "Recall and advisory standing",
        INCOMPLETE,
        INCOMPLETE_SEVERITY,
        "No status record is held, so recall standing is unknown.",
        reason_codes=["status_unknown"],
    )


def check_seller_authority(subject: dict) -> CheckResult:
    seller = seed.seller(subject.get("seller_ref", ""))
    if seller is None:
        return CheckResult(
            "seller_authority",
            "Seller authority",
            INCOMPLETE,
            INCOMPLETE_SEVERITY,
            "No seller record is held for this listing.",
            reason_codes=["seller_unknown"],
        )

    category = subject["category"]
    if seller["authority"] == "revoked":
        return CheckResult(
            "seller_authority",
            "Seller authority",
            FAIL,
            HARD_STOP,
            f"{seller['name']} has had its supply authority revoked.",
            reason_codes=["seller_authority_revoked"],
        )
    if seller["authority"] != "verified" or category not in seller["authorised_categories"]:
        return CheckResult(
            "seller_authority",
            "Seller authority",
            REVIEW,
            POLICY_DEPENDENT,
            f"{seller['name']} has no established authority to supply "
            f"{category.replace('_', ' ')}. This is an unknown, not a finding "
            "against the seller.",
            reason_codes=["seller_authority_unverified_for_category"],
        )
    return CheckResult(
        "seller_authority",
        "Seller authority",
        PASS,
        INFORMATIONAL,
        f"{seller['name']} is verified to supply {category.replace('_', ' ')}.",
    )


def check_mandatory_evidence(subject: dict) -> CheckResult:
    category = seed.category(subject["category"]) or {}
    required = category.get("required_evidence_types", [])
    records = _evidence_for(subject)
    present = {record["type"] for record in records}
    missing = [kind for kind in required if kind not in present]
    consulted = [record["ref"] for record in records]

    if missing:
        return CheckResult(
            "mandatory_evidence",
            "Mandatory evidence present",
            INCOMPLETE,
            INCOMPLETE_SEVERITY,
            f"Missing required evidence: {', '.join(missing)}.",
            reason_codes=["mandatory_evidence_missing"],
            evidence_consulted=consulted,
        )
    return CheckResult(
        "mandatory_evidence",
        "Mandatory evidence present",
        PASS,
        INFORMATIONAL,
        f"All {len(required)} required evidence type(s) are attached.",
        evidence_consulted=consulted,
    )


INTEGRITY_OUTCOME = {
    "verified": (PASS, INFORMATIONAL),
    "missing_metadata": (INCOMPLETE, INCOMPLETE_SEVERITY),
    "artefact_missing": (INCOMPLETE, INCOMPLETE_SEVERITY),
    "unknown_issuer_key": (INCOMPLETE, INCOMPLETE_SEVERITY),
    "unsafe_path": (FAIL, HARD_STOP),
    "hash_mismatch": (FAIL, HARD_STOP),
    "signature_invalid": (FAIL, HARD_STOP),
    "subject_scope_mismatch": (FAIL, HARD_STOP),
    "artefact_binding_mismatch": (FAIL, HARD_STOP),
}

INTEGRITY_REASON = {
    "missing_metadata": "evidence_integrity_metadata_missing",
    "artefact_missing": "evidence_artefact_missing",
    "unknown_issuer_key": "evidence_issuer_key_unknown",
    "unsafe_path": "evidence_storage_path_invalid",
    "hash_mismatch": "evidence_hash_mismatch",
    "signature_invalid": "evidence_signature_invalid",
    "subject_scope_mismatch": "evidence_subject_scope_mismatch",
    "artefact_binding_mismatch": "evidence_artefact_binding_mismatch",
}


def evaluate_evidence_integrity_bytes(
    record: dict,
    artefact_bytes: bytes,
    expected_subject_ref: str | None = None,
    subject_claims: list[dict] | None = None,
) -> dict:
    """Verify supplied artefact bytes and bind the structured decision metadata."""
    required = ("content_hash", "signature", "issuer_ref", "subject_ref")
    missing = [field for field in required if not record.get(field)]
    if missing:
        return {"state": "missing_metadata", "detail": f"integrity metadata missing: {', '.join(missing)}"}

    digest = hashlib.sha256(artefact_bytes).digest()
    computed_hash = "sha256:" + digest.hex()
    if computed_hash != record["content_hash"]:
        return {
            "state": "hash_mismatch",
            "detail": "artefact bytes do not match the signed content hash",
            "computed_hash": computed_hash,
        }

    public_key = keys.load_public_key(record["issuer_ref"])
    if public_key is None:
        return {"state": "unknown_issuer_key", "detail": "issuer public key is not in the embedded trust material"}
    try:
        signature = base64.b64decode(record["signature"], validate=True)
        public_key.verify(signature, digest)
    except (InvalidSignature, ValueError, TypeError):
        return {"state": "signature_invalid", "detail": "issuer Ed25519 signature does not verify"}

    try:
        text = artefact_bytes.decode("utf-8")
        binding_line = next(
            (line for line in text.splitlines()[:6] if line.startswith("binding-json: ")),
            None,
        )
        if binding_line is None:
            return {
                "state": "artefact_binding_mismatch",
                "detail": "signed artefact does not contain the required v2 metadata binding",
            }
        signed_binding = json.loads(binding_line.split(": ", 1)[1])
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return {
            "state": "artefact_binding_mismatch",
            "detail": "signed artefact metadata binding is malformed",
        }

    if subject_claims is None:
        subject = seed.subject(record.get("subject_ref", "")) or {}
        subject_claims = list(subject.get("claims", []))
    expected_binding = binding_payload(record, subject_claims)
    if signed_binding != expected_binding:
        return {
            "state": "artefact_binding_mismatch",
            "detail": "signed evidence binding disagrees with structured metadata or supported claim values",
        }

    expected = expected_subject_ref or record.get("subject_ref")
    scope = record.get("scope") or {}
    scoped_product = scope.get("product_ref")
    if record.get("subject_ref") != expected or (scoped_product and scoped_product != expected):
        return {"state": "subject_scope_mismatch", "detail": "evidence subject/scope does not match the assessed subject"}

    return {
        "state": "verified",
        "detail": "artefact hash and issuer Ed25519 signature verify; signed metadata/claim binding is consistent",
        "content_hash": computed_hash,
    }


def evaluate_evidence_integrity(
    record: dict,
    expected_subject_ref: str | None = None,
    subject_claims: list[dict] | None = None,
) -> dict:
    """Read the configured artefact safely, then verify its bytes."""
    if not record.get("storage_path"):
        return {"state": "missing_metadata", "detail": "integrity metadata missing: storage_path"}
    data_root = seed.DATA_DIR.resolve()
    artefact_path = (seed.DATA_DIR / record["storage_path"]).resolve()
    try:
        artefact_path.relative_to(data_root)
    except ValueError:
        return {"state": "unsafe_path", "detail": "artefact storage path escapes the demo data directory"}
    if not artefact_path.is_file():
        return {"state": "artefact_missing", "detail": f"artefact is missing: {record['storage_path']}"}
    return evaluate_evidence_integrity_bytes(
        record, artefact_path.read_bytes(), expected_subject_ref, subject_claims
    )


REQUIRED_EVIDENCE_FIELDS = (
    "ref",
    "claim_ref",
    "subject_ref",
    "issuer_ref",
    "issued_at",
    "valid_from",
    "retrieved_at",
    "record_status",
)

# Derived from the record's own dates and provenance against the snapshot. The
# dataset stores facts; it never stores whether something has expired.
FRESHNESS_OUTCOME = {
    "current": (PASS, INFORMATIONAL),
    "expired": (REVIEW, POLICY_DEPENDENT),
    "not_yet_valid": (REVIEW, POLICY_DEPENDENT),
    "missing_expiry": (REVIEW, POLICY_DEPENDENT),
    "revoked": (FAIL, HARD_STOP),
    "issuer_inactive": (FAIL, HARD_STOP),
    "malformed_record": (INCOMPLETE, INCOMPLETE_SEVERITY),
}

FRESHNESS_REASON = {
    "expired": "evidence_expired",
    "not_yet_valid": "evidence_not_yet_valid",
    "missing_expiry": "evidence_expiry_not_supplied",
    "revoked": "evidence_revoked",
    "issuer_inactive": "evidence_issuer_inactive",
    "malformed_record": "evidence_required_fields_missing",
}


def evaluate_evidence_freshness(record: dict, as_at) -> dict:
    """One evidence record's freshness state, derived from its own facts."""
    missing = sorted(f for f in REQUIRED_EVIDENCE_FIELDS if not record.get(f))
    if missing:
        return {
            "state": "malformed_record",
            "detail": f"record is missing {', '.join(missing)}",
            "missing_fields": missing,
        }

    issuer = seed.issuer(record["issuer_ref"])
    if issuer is None or issuer.get("status") != "active":
        name = issuer["name"] if issuer else record["issuer_ref"]
        return {"state": "issuer_inactive", "detail": f"{name} is no longer an active issuer"}

    if record["record_status"] in ("revoked", "withdrawn"):
        return {
            "state": "revoked",
            "detail": f"the issuer {record['record_status']} this certificate",
        }

    try:
        issued_at = seed.parse_timestamp(record["issued_at"])
        retrieved_at = seed.parse_timestamp(record["retrieved_at"])
        valid_from = seed.parse_timestamp(record["valid_from"])
    except (TypeError, ValueError):
        return {"state": "malformed_record", "detail": "one or more evidence timestamps are malformed"}

    if retrieved_at < issued_at:
        return {
            "state": "malformed_record",
            "detail": "retrieval timestamp precedes the evidence issue timestamp",
        }
    # Validate internal chronology before asking whether the record is current at
    # a particular assessment snapshot. Otherwise an impossible record whose
    # validity begins in the future could be misreported as merely not-yet-valid.
    if not record.get("expires_at"):
        return {"state": "missing_expiry", "detail": "no expiry date was supplied"}

    try:
        expires_at = seed.parse_timestamp(record["expires_at"])
    except (TypeError, ValueError):
        return {"state": "malformed_record", "detail": "expiry timestamp is malformed"}
    if expires_at < valid_from:
        return {"state": "malformed_record", "detail": "expiry timestamp precedes validity commencement"}
    if expires_at < issued_at:
        return {"state": "malformed_record", "detail": "expiry timestamp precedes the evidence issue timestamp"}

    if as_at < valid_from:
        return {
            "state": "not_yet_valid",
            "detail": f"does not take effect for another {(valid_from - as_at).days} days",
            "days_until_valid": (valid_from - as_at).days,
        }
    if as_at > expires_at:
        return {
            "state": "expired",
            "detail": f"expired {(as_at - expires_at).days} days ago",
            "days_expired": (as_at - expires_at).days,
        }

    return {
        "state": "current",
        "detail": f"valid for a further {(expires_at - as_at).days} days",
        "days_until_expiry": (expires_at - as_at).days,
    }


def check_evidence_freshness(subject: dict, artefact_overrides: dict[str, bytes] | None = None) -> CheckResult:
    as_at = seed.snapshot_date()
    records = _evidence_for(subject)

    if not records:
        return CheckResult(
            "evidence_freshness",
            "Evidence validity and integrity",
            INCOMPLETE,
            INCOMPLETE_SEVERITY,
            "There is no evidence whose validity could be checked.",
            reason_codes=["no_evidence_to_assess"],
        )

    claims = list(subject.get("claims", []))
    findings = []
    reason_codes: set[str] = set()
    consulted: list[str] = []
    outcome_rank = 0
    # Restrictiveness: pass < review < incomplete < fail.  Incomplete evidence
    # escalates rather than being softened by a merely reviewable validity issue,
    # while any established hard stop still dominates everything else.
    rank_to_result = {
        0: (PASS, INFORMATIONAL),
        1: (REVIEW, POLICY_DEPENDENT),
        2: (INCOMPLETE, INCOMPLETE_SEVERITY),
        3: (FAIL, HARD_STOP),
    }
    descriptions: list[str] = []

    for record in records:
        if artefact_overrides and record.get("ref") in artefact_overrides:
            integrity = evaluate_evidence_integrity_bytes(
                record, artefact_overrides[record["ref"]], subject.get("ref"), claims
            )
        else:
            integrity = evaluate_evidence_integrity(record, subject.get("ref"), claims)
        validity = evaluate_evidence_freshness(record, as_at)
        findings.append({
            "evidence_ref": record["ref"],
            "integrity": integrity,
            "freshness": validity,
        })
        consulted.append(record["ref"])

        i_outcome, _ = INTEGRITY_OUTCOME[integrity["state"]]
        v_outcome, _ = FRESHNESS_OUTCOME[validity["state"]]
        local_rank = max(
            {PASS: 0, REVIEW: 1, INCOMPLETE: 2, FAIL: 3}[i_outcome],
            {PASS: 0, REVIEW: 1, INCOMPLETE: 2, FAIL: 3}[v_outcome],
        )
        outcome_rank = max(outcome_rank, local_rank)

        if integrity["state"] != "verified":
            reason_codes.add(INTEGRITY_REASON[integrity["state"]])
            descriptions.append(f"{record['ref']} integrity: {integrity['detail']}")
        if validity["state"] != "current":
            code = FRESHNESS_REASON.get(validity["state"])
            if code:
                reason_codes.add(code)
            descriptions.append(f"{record['ref']} validity: {validity['detail']}")

    outcome, severity = rank_to_result[outcome_rank]
    if outcome_rank == 0:
        detail = (
            f"All {len(records)} evidence record(s) have verified signed bindings and are current at "
            f"{as_at.date().isoformat()}."
        )
    else:
        detail = "; ".join(descriptions) + "."

    return CheckResult(
        "evidence_freshness",
        "Evidence validity and integrity",
        outcome,
        severity,
        detail,
        reason_codes=sorted(reason_codes),
        evidence_consulted=consulted,
        findings=findings,
    )


_FRESHNESS_RANK = {
    "current": 0,
    "missing_expiry": 1,
    "not_yet_valid": 2,
    "expired": 3,
    "malformed_record": 4,
    "revoked": 5,
    "issuer_inactive": 6,
}


def check_claims_and_category(subject: dict) -> CheckResult:
    category = seed.category(subject["category"]) or {}
    required = category.get("required_claim_types", [])
    claims = subject.get("claims", [])
    consulted = [ref for claim in claims for ref in claim.get("evidence_refs", [])]

    rejected = [c for c in claims if c["state"] in ("rejected", "revoked")]
    if rejected:
        reasons = ", ".join(c.get("reason", c["state"]) for c in rejected)
        return CheckResult(
            "claims_and_category",
            "Claims and category requirements",
            FAIL,
            HARD_STOP,
            f"{len(rejected)} claim(s) rejected or revoked by the issuer: {reasons}.",
            reason_codes=["claim_rejected_or_revoked"],
            evidence_consulted=consulted,
        )

    present_types = {c["type"] for c in claims}
    missing = [kind for kind in required if kind not in present_types]
    if missing:
        return CheckResult(
            "claims_and_category",
            "Claims and category requirements",
            INCOMPLETE,
            INCOMPLETE_SEVERITY,
            f"No issuer has asserted the required claim(s): {', '.join(missing)}.",
            reason_codes=["required_claim_missing"],
            evidence_consulted=consulted,
        )

    binding_problems: list[str] = []
    for claim in claims:
        refs = claim.get("evidence_refs") or []
        if not refs:
            binding_problems.append(f"{claim['ref']} names no supporting evidence")
            continue
        for evidence_ref in refs:
            record = seed.evidence(evidence_ref)
            if record is None:
                binding_problems.append(f"{claim['ref']} references missing evidence {evidence_ref}")
                continue
            if record.get("subject_ref") != subject.get("ref"):
                binding_problems.append(f"{claim['ref']} evidence {evidence_ref} belongs to another subject")
            if record.get("issuer_ref") != claim.get("issuer_ref"):
                binding_problems.append(f"{claim['ref']} evidence {evidence_ref} is signed by a different issuer")
            supported = {record.get("claim_ref"), *(record.get("supports_claim_refs") or [])}
            supported.discard(None)
            if claim.get("ref") not in supported:
                binding_problems.append(f"{claim['ref']} is not named by evidence {evidence_ref}")
    if binding_problems:
        return CheckResult(
            "claims_and_category",
            "Claims and category requirements",
            FAIL,
            HARD_STOP,
            "Claim-to-evidence binding is inconsistent: " + "; ".join(binding_problems) + ".",
            reason_codes=["claim_evidence_binding_invalid"],
            evidence_consulted=consulted,
        )

    out_of_scope = []
    for claim in claims:
        issuer = seed.issuer(claim["issuer_ref"])
        if issuer and claim["type"] not in issuer["authority_scopes"]:
            out_of_scope.append((claim, issuer))
    if out_of_scope:
        described = ", ".join(
            f"{issuer['name']} asserting {claim['type']}" for claim, issuer in out_of_scope
        )
        return CheckResult(
            "claims_and_category",
            "Claims and category requirements",
            REVIEW,
            POLICY_DEPENDENT,
            f"Claim asserted outside the issuer's registered authority: {described}.",
            reason_codes=["claim_asserted_outside_issuer_authority"],
            evidence_consulted=consulted,
        )

    return CheckResult(
        "claims_and_category",
        "Claims and category requirements",
        PASS,
        INFORMATIONAL,
        f"All {len(required)} required claim type(s) present and asserted within "
        "issuer authority.",
        evidence_consulted=consulted,
    )


def _parse_omega3_components(value: object) -> dict[str, object] | None:
    """Parse EPA/DHA and, when present, the serving denominator/basis."""
    text = str(value or "")
    found: dict[str, object] = {}
    for component in ("EPA", "DHA"):
        match = re.search(rf"\b{component}\s*([0-9]+(?:\.[0-9]+)?)\s*mg\b", text, re.IGNORECASE)
        if not match:
            return None
        found[component] = float(match.group(1))
    serving = re.search(
        r"(?:per|/)\s*([0-9]+(?:\.[0-9]+)?)?\s*(capsule|capsules|softgel|softgels|tablet|tablets|serving|servings)\b",
        text, re.IGNORECASE,
    )
    if serving:
        found["denominator_count"] = float(serving.group(1) or 1.0)
        basis = serving.group(2).casefold()
        if basis.endswith("s"):
            basis = basis[:-1]
        found["denominator_basis"] = basis
    else:
        found["denominator_count"] = None
        found["denominator_basis"] = None
    return found


def _claim_values_conflict(claim_type: str, group: list[dict]) -> tuple[bool, str]:
    rule = (seed.policy_pack().get("claim_comparison") or {}).get(claim_type, {"mode": "exact"})
    mode = rule.get("mode", "exact")
    values = [claim.get("value") for claim in group]
    if mode == "omega3_mg_components":
        parsed = [_parse_omega3_components(value) for value in values]
        if all(item is not None for item in parsed):
            bases = {item["denominator_basis"] for item in parsed}
            counts = [item["denominator_count"] for item in parsed]
            # If both omit a denominator, preserve the existing demo semantics:
            # compare the stated EPA/DHA values on the same unstated basis.
            if bases == {None}:
                normalized = parsed
            # Mixed explicit/missing bases are not silently comparable.
            elif None in bases or len(bases) != 1 or any(c in (None, 0) for c in counts):
                return True, "policy comparison incomplete: incompatible or missing serving denominator"
            else:
                normalized = [
                    {
                        "EPA": float(item["EPA"]) / float(item["denominator_count"]),
                        "DHA": float(item["DHA"]) / float(item["denominator_count"]),
                    }
                    for item in parsed
                ]
            tolerance = float(rule.get("absolute_tolerance_mg", 0))
            components = ("EPA", "DHA")
            conflict = any(
                max(float(item[c]) for item in normalized) - min(float(item[c]) for item in normalized) > tolerance
                for c in components
            )
            return conflict, f"policy comparison: EPA/DHA absolute tolerance {tolerance:g} mg on a compatible serving basis"
    normalised = {str(value).strip().casefold() for value in values}
    return len(normalised) > 1, "policy comparison: exact normalised value"


def check_conflicting_information(subject: dict) -> CheckResult:
    claims = subject.get("claims", [])
    by_type: dict[str, list[dict]] = {}
    for claim in claims:
        by_type.setdefault(claim["type"], []).append(claim)

    conflicts = []
    for claim_type, group in by_type.items():
        if len(group) < 2:
            continue
        conflict, comparison = _claim_values_conflict(claim_type, group)
        if conflict:
            conflicts.append((claim_type, group, comparison))

    if conflicts:
        described = "; ".join(
            f"{claim_type} ({comparison}): "
            + " vs ".join(
                f"{(seed.issuer(c['issuer_ref']) or {'name': c['issuer_ref']})['name']} states {c['value']!r}"
                for c in group
            )
            for claim_type, group, comparison in conflicts
        )
        return CheckResult(
            "conflicting_information",
            "Conflicting information",
            REVIEW,
            POLICY_DEPENDENT,
            f"Issuers disagree. {described}.",
            reason_codes=["issuers_state_conflicting_values"],
            evidence_consulted=[
                ref for _, group, _ in conflicts for c in group for ref in c.get("evidence_refs", [])
            ],
        )

    if not claims:
        return CheckResult(
            "conflicting_information",
            "Conflicting information",
            INCOMPLETE,
            INCOMPLETE_SEVERITY,
            "There are no claims to compare.",
            reason_codes=["no_claims_to_compare"],
        )

    return CheckResult(
        "conflicting_information",
        "Conflicting information",
        PASS,
        INFORMATIONAL,
        "No two issuers state different values for the same claim type.",
    )


def run_all(subject: dict | None, identify_result: dict, status_result: dict, *, artefact_overrides: dict[str, bytes] | None = None) -> list[CheckResult]:
    """The seven checks, fixed order.

    With no resolved subject the remaining six report `incomplete` rather than
    being skipped — a check that did not run still belongs in the receipt.
    """
    identity = check_identity(identify_result)
    if subject is None:
        blanks = [
            ("standing", "Recall and advisory standing"),
            ("seller_authority", "Seller authority"),
            ("mandatory_evidence", "Mandatory evidence present"),
            ("evidence_freshness", "Evidence validity and integrity"),
            ("claims_and_category", "Claims and category requirements"),
            ("conflicting_information", "Conflicting information"),
        ]
        return [identity] + [
            CheckResult(
                check_id,
                label,
                INCOMPLETE,
                INCOMPLETE_SEVERITY,
                "Not run: no subject was resolved to check against.",
                reason_codes=["not_run_identity_unresolved"],
            )
            for check_id, label in blanks
        ]

    return [
        identity,
        check_standing(status_result),
        check_seller_authority(subject),
        check_mandatory_evidence(subject),
        check_evidence_freshness(subject, artefact_overrides=artefact_overrides),
        check_claims_and_category(subject),
        check_conflicting_information(subject),
    ]
