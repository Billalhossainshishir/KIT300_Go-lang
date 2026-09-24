"""RESOLVE — component 2. `identify`, `resolve`, `status`.

What a thing is and where it stands. Whether it can be trusted is RATIFY's
job; keeping the two apart is what lets a verdict be replayed a step at a time.
"""

from ramify.crypto.canonical import rfc3339_nano
from ramify.data import seed
from ramify.timing import now

FRESHNESS_TTL_SECONDS = 3600


def identify(identifier: str) -> dict:
    """Resolve an exact local identifier to one canonical subject.

    This primitive is deterministic, so it does not report a probability or
    ``confidence``.  Explicit namespaces (``gtin:``, ``sku:``, ``local:``) are
    honoured rather than stripped and then matched against every identifier
    field.  An unqualified value may match any exact identifier, but ambiguous
    matches are returned for disambiguation instead of being guessed.
    """
    raw = str(identifier or "").strip()
    probe = raw.lower()

    namespace = None
    value = probe
    for prefix, field in (("gtin:", "gtin"), ("sku:", "sku"), ("local:", "local")):
        if probe.startswith(prefix):
            namespace = field
            value = probe[len(prefix):].strip()
            break

    matches: list[str] = []
    match_methods: dict[str, str] = {}
    for ref, record in seed.subjects().items():
        identifiers = record.get("identifiers") or {}
        if namespace is not None:
            candidate = identifiers.get(namespace)
            if candidate is not None and str(candidate).strip().lower() == value:
                matches.append(ref)
                match_methods[ref] = f"exact_{namespace}"
            continue

        if ref.lower() == value:
            matches.append(ref)
            match_methods[ref] = "exact_subject_ref"
            continue
        for field, candidate in identifiers.items():
            if candidate is not None and str(candidate).strip().lower() == value:
                matches.append(ref)
                match_methods[ref] = f"exact_{field}"
                break

    # Preserve catalogue order while eliminating accidental duplicates.
    matches = list(dict.fromkeys(matches))

    if len(matches) == 1:
        ref = matches[0]
        subject = seed.subject(ref)
        return {
            "subject_ref": ref,
            "product_name": subject["name"],
            "match_method": match_methods.get(ref, "exact_identifier"),
            "resolved": True,
            "candidates": [ref],
            "next_action": "resolve",
        }

    if len(matches) > 1:
        return {
            "subject_ref": None,
            "product_name": None,
            "match_method": "ambiguous_exact_identifier",
            "resolved": False,
            "candidates": sorted(matches),
            "next_action": "disambiguate",
        }

    return {
        "subject_ref": None,
        "product_name": None,
        "match_method": "no_exact_match",
        "resolved": False,
        "candidates": [],
        "next_action": "indeterminate",
    }


def resolve(subject_ref: str) -> dict:
    """The read projection for a subject.

    An unrecognised one returns `observed` per spec 6.7 — the identifier has
    been seen and nothing more is known.
    """
    subject = seed.subject(subject_ref)
    generated_at = rfc3339_nano(now())

    if subject is None:
        return {
            "subject_ref": subject_ref,
            "canonical_state": "observed",
            "identifiers": {},
            "freshness": {
                "generated_at": generated_at,
                "ttl_seconds": FRESHNESS_TTL_SECONDS,
                "data_snapshot": seed.snapshot_id(),
            },
            "known": False,
        }

    record = {
        "subject_ref": subject_ref,
        "canonical_state": "asserted" if subject.get("claims") else "observed",
        "product_name": subject["name"],
        "brand": subject["brand"],
        "category": subject["category"],
        "seller_ref": subject["seller_ref"],
        "identifiers": subject["identifiers"],
        "freshness": {
            "generated_at": generated_at,
            "ttl_seconds": FRESHNESS_TTL_SECONDS,
            "data_snapshot": seed.snapshot_id(),
        },
        "known": True,
    }
    if subject.get("batch_ref"):
        record["batch_ref"] = subject["batch_ref"]
    if subject.get("superseded_by"):
        record["superseded_by"] = subject["superseded_by"]
        record["supersession_note"] = subject.get("supersession_note", "")
    if subject.get("supersedes"):
        record["supersedes"] = subject["supersedes"]
    return record


def status(subject_ref: str) -> dict:
    """Current standing against the local status feed.

    No record returns `unknown`, which is deliberately not `no_active_recall`.
    Absence of a notice is not evidence that none exists.
    """
    record = seed.status_for(subject_ref)
    if record is None:
        return {
            "subject_ref": subject_ref,
            "standing": "unknown",
            "scope": "product",
            "issuer_ref": None,
            "reason": "no_status_record_held",
            "detail": "No status record is held for this subject.",
            "issued_at": None,
        }

    result = {
        "subject_ref": subject_ref,
        "standing": record["standing"],
        "scope": record["scope"],
        "issuer_ref": record["issuer_ref"],
        "reason": record.get("reason", ""),
        "detail": record.get("detail", ""),
        "issued_at": record["issued_at"],
    }
    if record.get("batch_ref"):
        result["batch_ref"] = record["batch_ref"]
    return result
