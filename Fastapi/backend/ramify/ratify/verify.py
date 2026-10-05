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


def _claim_verdict(claim: dict, as_at, subject_ref: str) -> tuple[str, list[str]]:
    if claim["state"] in ("rejected", "revoked"):
        reason = claim.get("reason")
        return claim["state"], [reason] if reason else []

    reason_codes: list[str] = []
    severe = False
    revoked = False
    # A claim naming no evidence used to fall straight through the loop below
    # and come out "accepted" while the aggregate check failed it (David's E3).
    if not claim.get("evidence_refs"):
        reason_codes.append("claim_has_no_evidence")
        severe = True
    for ref in claim.get("evidence_refs", []):
        record = seed.evidence(ref)
        if record is None:
            reason_codes.append("evidence_artefact_missing")
            severe = True
            continue

        binding_ok = True
        if record.get("subject_ref") != subject_ref or record.get("issuer_ref") != claim.get("issuer_ref"):
            binding_ok = False
        if claim.get("ref") not in ratify_checks.supported_claim_refs(record):
            binding_ok = False
        if not binding_ok:
            if "claim_evidence_binding_invalid" not in reason_codes:
                reason_codes.append("claim_evidence_binding_invalid")
            severe = True

        integrity = ratify_checks.evaluate_evidence_integrity(record, subject_ref)
        if integrity["state"] != "verified":
            code = ratify_checks.INTEGRITY_REASON.get(integrity["state"], "evidence_integrity_unverified")
            if code not in reason_codes:
                reason_codes.append(code)
            severe = severe or integrity["state"] in {
                "unsafe_path", "hash_mismatch", "signature_invalid", "subject_scope_mismatch",
                "artefact_binding_mismatch"
            }
        elif binding_ok:
            # Integrity verified, so the header can be trusted: the claim's own
            # state and value must be what the issuer signed (David's E1).
            assertion = (ratify_checks.signed_claim_assertions(record, subject_ref) or {}).get(claim["ref"])
            if (
                assertion is None
                or assertion["state"] != claim.get("state")
                or assertion["value"] != claim.get("value")
            ):
                if "claim_evidence_binding_invalid" not in reason_codes:
                    reason_codes.append("claim_evidence_binding_invalid")
                severe = True

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


def claim_results(subject: dict) -> list[dict]:
    as_at = seed.snapshot_date()
    results = []
    for claim in subject.get("claims", []):
        verdict, reason_codes = _claim_verdict(claim, as_at, subject["ref"])
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


def verify(subject_ref: str, policy_ref: str, identify_result: dict, status_result: dict) -> dict:
    """Run RATIFY over a subject and return both views.

    A caller may name the policy it expects, but only to be checked against the
    pack that is actually evaluated. Echoing an unchecked caller-supplied value
    into the receipt let a sealed, cryptographically valid receipt attest to a
    policy that had never been applied, which is the one thing the receipt
    exists to state truthfully.
    """
    subject = seed.subject(subject_ref)
    pack = seed.policy_pack()
    if policy_ref and policy_ref != pack["policy_ref"]:
        raise ValueError(
            f"Unknown policy reference {policy_ref!r}. This build evaluates "
            f"{pack['policy_ref']!r} and cannot assess against any other pack."
        )
    results = ratify_checks.run_all(subject, identify_result, status_result)

    return {
        "subject_ref": subject_ref,
        # The pack that was evaluated, never the caller's label for it.
        "policy_ref": pack["policy_ref"],
        "policy_version": pack["policy_version"],
        "policy_status": pack["status"],
        # Content identities. The version and snapshot labels above can stay
        # the same while the rules or data change; these cannot.
        "policy_digest": seed.policy_digest(),
        "dataset_digest": seed.dataset_digest(),
        "check_results": [check.as_dict() for check in results],
        "claim_results": claim_results(subject) if subject else [],
    }
