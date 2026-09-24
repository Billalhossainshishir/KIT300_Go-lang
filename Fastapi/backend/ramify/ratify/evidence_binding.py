"""Canonical binding between signed evidence artefacts and structured metadata.

The synthetic artefact signature is only useful for a decision when the fields
that drive RATIFY are bound to the signed bytes.  This module builds one
canonical payload from the evidence record plus the exact claims that record
supports.  Seed generation embeds the payload in the signed artefact; runtime
verification recomputes it from the current structured data and rejects any
mismatch.
"""

from __future__ import annotations

import json

BINDING_SCHEMA = "ramify-evidence-binding-v2"
_GENERATED_FIELDS = {"content_hash", "signature", "storage_path"}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def binding_payload(record: dict, subject_claims: list[dict] | None = None) -> dict:
    """Return the decision-relevant structured payload authenticated by the artefact.

    All evidence metadata from the dataset is covered except the generated
    cryptographic/storage fields.  Claim references are additionally resolved
    to the exact claim assertions (value/state/type/issuer) so changing a claim
    while leaving the evidence bytes/signature untouched is detectable.
    """
    metadata = {
        key: value
        for key, value in record.items()
        if key not in _GENERATED_FIELDS
    }

    refs = [record.get("claim_ref"), *(record.get("supports_claim_refs") or [])]
    refs = sorted({ref for ref in refs if ref})
    claims_by_ref = {
        claim.get("ref"): claim
        for claim in (subject_claims or [])
        if isinstance(claim, dict) and claim.get("ref")
    }
    supported_claims = {}
    for ref in refs:
        claim = claims_by_ref.get(ref)
        if claim is None:
            supported_claims[ref] = None
        else:
            supported_claims[ref] = {
                "ref": claim.get("ref"),
                "type": claim.get("type"),
                "issuer_ref": claim.get("issuer_ref"),
                "state": claim.get("state"),
                "value": claim.get("value"),
            }

    return {
        "schema": BINDING_SCHEMA,
        "record": metadata,
        "supported_claims": supported_claims,
    }


def encoded_binding(record: dict, subject_claims: list[dict] | None = None) -> str:
    return canonical_json(binding_payload(record, subject_claims))
