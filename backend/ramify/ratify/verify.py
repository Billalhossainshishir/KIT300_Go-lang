"""The `verify` primitive.

Runs the seven checks and, separately, reports a verdict per claim. The two
views answer different questions. The checks say what the system examined; the
claim verdicts say what each issuer's assertion is now worth.

Claim verdicts use the specification's vocabulary: `accepted`,
`accepted_with_scope_limit`, `rejected`, `revoked`. A claim resting on expired
evidence becomes `accepted_with_scope_limit` rather than `rejected`, because
the finding the lab recorded still stands — what lapsed is the assurance that
it remains current.
"""

from ramify.data import seed
from ramify.ratify import checks as ratify_checks


def _claim_verdict(
    claim: dict, as_at, subject_ref: str, subject_claims: list[dict],
    artefact_overrides: dict[str, bytes] | None = None,
) -> tuple[str, list[str]]:
    if claim["state"] in ("rejected", "revoked"):
        reason = claim.get("reason")
        return claim["state"], [reason] if reason else []

    if not claim.get("evidence_refs"):
        return "rejected", ["claim_evidence_missing"]

    reason_codes: list[str] = []
    severe = False
    revoked = False
    for ref in claim.get("evidence_refs", []):
        record = seed.evidence(ref)
        if record is None:
            reason_codes.append("evidence_artefact_missing")
            severe = True
            continue

        binding_ok = True
        if record.get("subject_ref") != subject_ref or record.get("issuer_ref") != claim.get("issuer_ref"):
            binding_ok = False
        supported = {record.get("claim_ref"), *(record.get("supports_claim_refs") or [])}
        supported.discard(None)
        if claim.get("ref") not in supported:
            binding_ok = False
        if not binding_ok:
            if "claim_evidence_binding_invalid" not in reason_codes:
                reason_codes.append("claim_evidence_binding_invalid")
            severe = True

        if artefact_overrides and ref in artefact_overrides:
            integrity = ratify_checks.evaluate_evidence_integrity_bytes(
                record, artefact_overrides[ref], subject_ref, subject_claims
            )
        else:
            integrity = ratify_checks.evaluate_evidence_integrity(record, subject_ref, subject_claims)
        if integrity["state"] != "verified":
            code = ratify_checks.INTEGRITY_REASON.get(integrity["state"], "evidence_integrity_unverified")
            if code not in reason_codes:
                reason_codes.append(code)
            severe = severe or integrity["state"] in {
                "unsafe_path", "hash_mismatch", "signature_invalid", "subject_scope_mismatch",
                "artefact_binding_mismatch"
            }

        freshness = ratify_checks.evaluate_evidence_freshness(record, as_at)
        state = freshness["state"]
        if state != "current":
            code = ratify_checks.FRESHNESS_REASON.get(state)
            if code and code not in reason_codes:
                reason_codes.append(code)
            if state == "revoked":
                revoked = True
            severe = severe or state in {"revoked", "issuer_inactive"}

    issuer = seed.issuer(claim["issuer_ref"])
    if issuer is None or issuer.get("status") != "active":
        if "evidence_issuer_inactive" not in reason_codes:
            reason_codes.append("evidence_issuer_inactive")
        severe = True
    elif claim["type"] not in issuer["authority_scopes"]:
        reason_codes.append("asserted_outside_issuer_authority")

    if revoked:
        return "revoked", reason_codes
    if severe:
        return "rejected", reason_codes
    if reason_codes:
        return "accepted_with_scope_limit", reason_codes
    return "accepted", []


def claim_results(subject: dict, artefact_overrides: dict[str, bytes] | None = None) -> list[dict]:
    as_at = seed.snapshot_date()
    results = []
    claims = list(subject.get("claims", []))
    for claim in claims:
        verdict, reason_codes = _claim_verdict(claim, as_at, subject["ref"], claims, artefact_overrides)
        issuer = seed.issuer(claim["issuer_ref"])
        results.append(
            {
                "claim_ref": claim["ref"],
                "type": claim["type"],
                "verdict": verdict,
                "value": claim.get("value", ""),
                "issuer_ref": claim["issuer_ref"],
                "issuer_name": issuer["name"] if issuer else "unknown issuer",
                "evidence_refs": list(claim.get("evidence_refs", [])),
                "reason_codes": reason_codes,
            }
        )
    return results


def verify(
    subject_ref: str, policy_ref: str | None, identify_result: dict, status_result: dict,
    *, artefact_overrides: dict[str, bytes] | None = None,
) -> dict:
    """Run RATIFY over a subject and identify the exact decision inputs."""
    subject = seed.subject(subject_ref)
    pack = seed.policy_pack()
    requested = policy_ref or pack["policy_ref"]
    if requested != pack["policy_ref"]:
        raise ValueError(f"Unsupported policy_ref: {requested}")
    results = ratify_checks.run_all(
        subject, identify_result, status_result, artefact_overrides=artefact_overrides
    )

    return {
        "subject_ref": subject_ref,
        "policy_ref": pack["policy_ref"],
        "policy_version": pack["policy_version"],
        "policy_status": pack["status"],
        "policy_digest": seed.policy_digest(),
        "data_snapshot": seed.snapshot_id(),
        "dataset_digest": seed.dataset_digest(),
        "check_results": [check.as_dict() for check in results],
        "claim_results": claim_results(subject, artefact_overrides) if subject else [],
    }

