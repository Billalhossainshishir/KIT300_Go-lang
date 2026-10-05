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
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from cryptography.exceptions import InvalidSignature

from ramify.crypto import keys
from ramify.data import seed

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

    # A status record that does not match what its issuer signed cannot be
    # read as clean, whatever its standing field now says.
    integrity = status_result.get("integrity")
    if integrity in RECORD_TAMPER_STATES:
        return CheckResult(
            "standing",
            "Recall and advisory standing",
            FAIL,
            HARD_STOP,
            "The recall status record does not match what the issuer signed, so its standing cannot be relied on.",
            reason_codes=["status_record_integrity_failed"],
        )
    if integrity == "missing_signature":
        return CheckResult(
            "standing",
            "Recall and advisory standing",
            INCOMPLETE,
            INCOMPLETE_SEVERITY,
            "The recall status record carries no issuer signature, so its standing is unconfirmed.",
            reason_codes=["status_record_unsigned"],
        )

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

    integrity = evaluate_record_integrity("sellers", subject.get("seller_ref", ""), seller)["state"]
    if integrity in RECORD_TAMPER_STATES:
        return CheckResult(
            "seller_authority",
            "Seller authority",
            FAIL,
            HARD_STOP,
            f"The seller record for {seller.get('name', 'this seller')} does not match what the issuer signed.",
            reason_codes=["seller_record_integrity_failed"],
        )
    if integrity == "missing_signature":
        return CheckResult(
            "seller_authority",
            "Seller authority",
            INCOMPLETE,
            INCOMPLETE_SEVERITY,
            f"The seller record for {seller.get('name', 'this seller')} carries no issuer signature.",
            reason_codes=["seller_record_unsigned"],
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


# Where evidence artefacts are read from. The tamper demonstration points its
# own assessment at a temporary copy and every other request keeps reading the
# shipped files. A context variable belongs to one request, so nothing is
# shared and no shipped artefact is ever written (David's U2). This replaces a
# lock that only serialised the demonstration's edits to the shipped file,
# which a process killed mid-demonstration could still leave modified.
_ARTEFACT_ROOT: ContextVar[Path | None] = ContextVar("ramify_artefact_root", default=None)


def artefact_root() -> Path:
    return _ARTEFACT_ROOT.get() or seed.DATA_DIR


@contextmanager
def artefacts_from(root: Path):
    """Read evidence artefacts from ``root`` for the current request only."""
    token = _ARTEFACT_ROOT.set(root)
    try:
        yield
    finally:
        _ARTEFACT_ROOT.reset(token)

# Ordered by the posture each outcome leads to, not by how alarming the word
# sounds: review gives allow_with_warning, incomplete gives escalate. Ranking
# review above incomplete let expired evidence with missing integrity metadata
# combine to allow_with_warning, so an ordinary warning erased the integrity
# stop (David, 1 Oct, item 2).
_OUTCOME_STRICTNESS = {PASS: 0, REVIEW: 1, INCOMPLETE: 2, FAIL: 3}
_SEVERITY_STRICTNESS = {
    INFORMATIONAL: 0,
    INCOMPLETE_SEVERITY: 1,
    POLICY_DEPENDENT: 2,
    HARD_STOP: 3,
}


def _strictness(graded: tuple[str, str]) -> tuple[int, int]:
    """Order an (outcome, severity) pair so the strictest one can be taken."""
    outcome, severity = graded
    return _OUTCOME_STRICTNESS[outcome], _SEVERITY_STRICTNESS[severity]


def parse_signed_header(text: str) -> dict[str, str]:
    """The ``key: value`` lines of a signed artefact, up to the first blank line."""
    headers: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        if not line.strip():
            break
        if ": " in line:
            key, value = line.split(": ", 1)
            headers[key.strip().lower()] = value.strip()
    return headers


def supported_claim_refs(record: dict) -> list[str]:
    """The claims an evidence record says it supports, in signed-header order."""
    refs = {record.get("claim_ref"), *(record.get("supports_claim_refs") or [])}
    refs.discard(None)
    return sorted(refs)


def signed_claim_assertions(record: dict, expected_subject_ref: str | None = None) -> dict | None:
    """What the issuer signed about each supported claim, or None if unverified.

    Returns ``{claim_ref: {"state": ..., "value": ...}}`` read from the signed
    artefact header, only once that artefact's integrity has verified.
    """
    if evaluate_evidence_integrity(record, expected_subject_ref)["state"] != "verified":
        return None
    text = (artefact_root() / record["storage_path"]).resolve().read_text(encoding="utf-8")
    headers = parse_signed_header(text)
    assertions: dict[str, dict] = {}
    for ref in supported_claim_refs(record):
        key = ref.lower()
        if f"claim-state {key}" in headers or f"claim-value {key}" in headers:
            assertions[ref] = {
                "state": headers.get(f"claim-state {key}"),
                "value": headers.get(f"claim-value {key}"),
            }
    return assertions


# Issuer that attests seller-authority records, which do not name one
# themselves. Recall-status records are signed by the issuer they name.
SELLER_AUTHORITY_ISSUER = "ramify:demo:issuer:Regulator_AU_demo"
RECORD_TAMPER_STATES = frozenset({"hash_mismatch", "signature_invalid", "issuer_mismatch", "unknown_issuer_key"})


def evaluate_record_integrity(kind: str, ref: str, record: dict) -> dict:
    """Verify a recall-status or seller-authority record against its issuer signature.

    These records decide a verdict as directly as evidence does: a recall is
    the headline hard stop and seller authority can block a sale. They used to
    be trusted as plain JSON, so editing one record turned a recalled product
    into an allowed one (26 September audit, N4). ``kind`` is ``statuses`` or
    ``sellers``.
    """
    meta = (seed.record_signatures().get(kind) or {}).get(ref)
    if not meta:
        return {"state": "missing_signature", "detail": f"no issuer signature is held for this {kind[:-1]} record"}
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(canonical).digest()
    if "sha256:" + digest.hex() != meta.get("content_hash"):
        return {"state": "hash_mismatch", "detail": f"the {kind[:-1]} record differs from what the issuer signed"}
    expected_issuer = record.get("issuer_ref") if kind == "statuses" else SELLER_AUTHORITY_ISSUER
    if meta.get("issuer_ref") != expected_issuer:
        return {"state": "issuer_mismatch", "detail": "the record was signed by a different issuer"}
    public_key = keys.load_public_key(meta["issuer_ref"])
    if public_key is None:
        return {"state": "unknown_issuer_key", "detail": "issuer public key is not in the embedded trust material"}
    try:
        public_key.verify(base64.b64decode(meta.get("signature", ""), validate=True), digest)
    except (InvalidSignature, ValueError, TypeError):
        return {"state": "signature_invalid", "detail": "issuer Ed25519 signature does not verify"}
    return {"state": "verified", "detail": "record hash and issuer Ed25519 signature verify"}


def evaluate_evidence_integrity(record: dict, expected_subject_ref: str | None = None) -> dict:
    """Cryptographically verify the synthetic evidence artefact and its binding.

    The evidence manifest is not treated as proof by itself: RAMIFY opens the
    artefact bytes, recomputes SHA-256, verifies the issuer Ed25519 signature
    over that digest, then checks that the record/scope still point at the
    subject being assessed.
    """
    required = ("content_hash", "signature", "storage_path", "issuer_ref", "subject_ref")
    missing = [field for field in required if not record.get(field)]
    if missing:
        return {"state": "missing_metadata", "detail": f"integrity metadata missing: {', '.join(missing)}"}

    data_root = artefact_root().resolve()
    artefact_path = (data_root / record["storage_path"]).resolve()
    try:
        artefact_path.relative_to(data_root)
    except ValueError:
        return {"state": "unsafe_path", "detail": "artefact storage path escapes the demo data directory"}
    if not artefact_path.is_file():
        return {"state": "artefact_missing", "detail": f"artefact is missing: {record['storage_path']}"}
    artefact_bytes = artefact_path.read_bytes()
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

    # The signed artefact itself carries issuer/subject/date headers. Compare
    # those signed bytes with the structured metadata so changing both
    # ``subject_ref`` and ``scope.product_ref`` cannot make an unrelated signed
    # artefact appear bound to the product being assessed.
    try:
        headers = parse_signed_header(artefact_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        return {"state": "artefact_binding_mismatch", "detail": "signed artefact header is not valid UTF-8"}

    # Every field that decides a verdict is compared with what the issuer
    # signed. Validity start, record status and the supported claims used to
    # sit outside the signature, so a one-word manifest edit could clear a
    # revoked certificate while integrity still reported verified (David's E1).
    expected_headers = {
        "issuer": str(record.get("issuer_ref", "")),
        "subject": str(record.get("subject_ref", "")),
        "issued": str(record.get("issued_at", "")),
        "expires": str(record.get("expires_at", "")),
        "valid_from": str(record.get("valid_from", "")),
        "status": str(record.get("record_status", "")),
        "supports": ", ".join(supported_claim_refs(record)),
    }
    mismatched = [
        key for key, value in expected_headers.items()
        if headers.get(key) != value
    ]
    if mismatched:
        return {
            "state": "artefact_binding_mismatch",
            "detail": "signed artefact header disagrees with structured metadata: " + ", ".join(mismatched),
        }

    expected = expected_subject_ref or record.get("subject_ref")
    scope = record.get("scope") or {}
    scoped_product = scope.get("product_ref")
    if record.get("subject_ref") != expected or (scoped_product and scoped_product != expected):
        return {"state": "subject_scope_mismatch", "detail": "evidence subject/scope does not match the assessed subject"}

    return {
        "state": "verified",
        "detail": "artefact hash and issuer Ed25519 signature verify; subject/scope binding is consistent",
        "content_hash": computed_hash,
    }


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
    if valid_from < issued_at:
        return {
            "state": "malformed_record",
            "detail": "validity commencement precedes the evidence issue timestamp",
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
    if expires_at <= valid_from:
        return {"state": "malformed_record", "detail": "expiry timestamp does not follow validity commencement"}
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


def check_evidence_freshness(subject: dict) -> CheckResult:
    as_at = seed.snapshot_date()
    records = _evidence_for(subject)

    if not records:
        return CheckResult(
            "evidence_freshness",
            "Evidence validity and integrity",
            INCOMPLETE,
            INCOMPLETE_SEVERITY,
            "There is no evidence whose freshness could be checked.",
            reason_codes=["no_evidence_to_assess"],
        )

    integrity_states = [
        (record, evaluate_evidence_integrity(record, subject.get("ref"))) for record in records
    ]
    integrity_problems = [(r, finding) for r, finding in integrity_states if finding["state"] != "verified"]
    if integrity_problems:
        # Integrity and freshness are separate axes and one record can fail on
        # both. Deciding on integrity alone let a weaker defect hide a stronger
        # one: a revoked certificate is a hard stop, missing integrity metadata
        # is merely incomplete, and a record with both came out incomplete. That
        # made the result weaker for having one more thing wrong with it, and it
        # dropped the revocation reason from the output entirely.
        #
        # So both axes are evaluated and the strictest safely established
        # outcome wins, carrying every reason that was found.
        freshness_states = [(r, evaluate_evidence_freshness(r, as_at)) for r in records]
        freshness_problems = [(r, f) for r, f in freshness_states if f["state"] != "current"]

        graded = [INTEGRITY_OUTCOME[f["state"]] for _, f in integrity_problems]
        graded += [FRESHNESS_OUTCOME[f["state"]] for _, f in freshness_problems]
        outcome, severity = max(graded, key=_strictness)

        reason_codes = {INTEGRITY_REASON[f["state"]] for _, f in integrity_problems}
        reason_codes |= {FRESHNESS_REASON[f["state"]] for _, f in freshness_problems}

        described = "; ".join(f"{r['ref']} {finding['detail']}" for r, finding in integrity_problems)
        also = "; ".join(f"{r['ref']} {f['detail']}" for r, f in freshness_problems)
        summary = f"Evidence integrity could not be established: {described}."
        if also:
            summary += f" Validity also failed: {also}."
        return CheckResult(
            "evidence_freshness",
            "Evidence validity and integrity",
            outcome,
            severity,
            summary,
            reason_codes=sorted(reason_codes),
            evidence_consulted=sorted(
                {r["ref"] for r, _ in integrity_problems} | {r["ref"] for r, _ in freshness_problems}
            ),
            findings=[
                {
                    "evidence_ref": r["ref"],
                    "integrity": finding,
                    "freshness": evaluate_evidence_freshness(r, as_at),
                }
                for r, finding in integrity_states
            ],
        )

    states = [(record, evaluate_evidence_freshness(record, as_at)) for record in records]
    problems = [(r, f) for r, f in states if f["state"] != "current"]

    if not problems:
        return CheckResult(
            "evidence_freshness",
            "Evidence validity and integrity",
            PASS,
            INFORMATIONAL,
            f"All {len(records)} evidence record(s) are current at "
            f"{as_at.date().isoformat()}.",
            evidence_consulted=[r["ref"] for r in records],
            findings=[
                {"evidence_ref": r["ref"], **f, "integrity": evaluate_evidence_integrity(r, subject.get("ref"))}
                for r, f in states
            ],
        )

    # Several records can be unusable for different reasons at once. The check
    # takes the worst outcome and reports every reason, rather than stopping at
    # the first problem it finds.
    worst = max(problems, key=lambda pair: _FRESHNESS_RANK[pair[1]["state"]])
    outcome, severity = FRESHNESS_OUTCOME[worst[1]["state"]]
    described = "; ".join(f"{r['document_type'].replace('_', ' ')} {f['detail']}" for r, f in problems)

    return CheckResult(
        "evidence_freshness",
        "Evidence validity and integrity",
        outcome,
        severity,
        f"{described}. Derived from the record's own dates against the "
        f"{as_at.date().isoformat()} snapshot.",
        reason_codes=sorted({FRESHNESS_REASON[f["state"]] for _, f in problems}),
        evidence_consulted=[r["ref"] for r, _ in problems],
        findings=[
            {"evidence_ref": r["ref"], **f, "integrity": evaluate_evidence_integrity(r, subject.get("ref"))}
            for r, f in states
        ],
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

    # Every rule is evaluated and the strictest outcome is reported with all
    # of its reasons. Returning at the first finding let a missing required
    # claim (incomplete) hide another claim's broken evidence binding (a hard
    # stop), so the weaker result won for having more wrong (David, 1 Oct).
    findings: list[tuple[str, str, str, str]] = []

    rejected = [c for c in claims if c["state"] in ("rejected", "revoked")]
    if rejected:
        reasons = ", ".join(c.get("reason", c["state"]) for c in rejected)
        findings.append((
            FAIL, HARD_STOP, "claim_rejected_or_revoked",
            f"{len(rejected)} claim(s) rejected or revoked by the issuer: {reasons}.",
        ))

    present_types = {c["type"] for c in claims}
    missing = [kind for kind in required if kind not in present_types]
    if missing:
        findings.append((
            INCOMPLETE, INCOMPLETE_SEVERITY, "required_claim_missing",
            f"No issuer has asserted the required claim(s): {', '.join(missing)}.",
        ))

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
            if claim.get("ref") not in supported_claim_refs(record):
                binding_problems.append(f"{claim['ref']} is not named by evidence {evidence_ref}")
                continue
            # The claim's own state and value must be what the issuer signed.
            # When the artefact does not verify, evidence_freshness already
            # reports that, so nothing is added here.
            signed = signed_claim_assertions(record, subject.get("ref"))
            if signed is not None:
                assertion = signed.get(claim["ref"])
                if assertion is None:
                    binding_problems.append(
                        f"{claim['ref']} is not asserted in signed evidence {evidence_ref}")
                elif assertion["state"] != claim.get("state") or assertion["value"] != claim.get("value"):
                    binding_problems.append(
                        f"{claim['ref']} differs from what signed evidence {evidence_ref} asserts")
    if binding_problems:
        findings.append((
            FAIL, HARD_STOP, "claim_evidence_binding_invalid",
            "Claim-to-evidence binding is inconsistent: " + "; ".join(binding_problems) + ".",
        ))

    out_of_scope = []
    for claim in claims:
        issuer = seed.issuer(claim["issuer_ref"])
        if issuer and claim["type"] not in issuer["authority_scopes"]:
            out_of_scope.append((claim, issuer))
    if out_of_scope:
        described = ", ".join(
            f"{issuer['name']} asserting {claim['type']}" for claim, issuer in out_of_scope
        )
        findings.append((
            REVIEW, POLICY_DEPENDENT, "claim_asserted_outside_issuer_authority",
            f"Claim asserted outside the issuer's registered authority: {described}.",
        ))

    if findings:
        outcome, severity = max(((f[0], f[1]) for f in findings), key=_strictness)
        return CheckResult(
            "claims_and_category",
            "Claims and category requirements",
            outcome,
            severity,
            " ".join(f[3] for f in findings),
            reason_codes=[f[2] for f in findings],
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


def _parse_omega3_components(value: object) -> dict[str, float] | None:
    text = str(value or "")
    found = {}
    for component in ("EPA", "DHA"):
        match = re.search(rf"\b{component}\s*([0-9]+(?:\.[0-9]+)?)\s*mg\b", text, re.IGNORECASE)
        if not match:
            return None
        found[component] = float(match.group(1))
    return found


def _serving_basis(value: object) -> tuple[float, str] | None:
    """``per 2 softgels`` -> (2.0, "softgel"); None when no basis is stated."""
    match = re.search(r"\bper\s+(?:([0-9]+(?:\.[0-9]+)?)\s*)?([a-z]+)", str(value or ""), re.IGNORECASE)
    if not match:
        return None
    count = float(match.group(1)) if match.group(1) else 1.0
    unit = match.group(2).lower()
    return count, unit[:-1] if unit.endswith("s") else unit


def _claim_values_conflict(claim_type: str, group: list[dict]) -> tuple[str, str]:
    """Compare claim values: ``conflict``, ``consistent`` or ``incomparable``."""
    rule = (seed.policy_pack().get("claim_comparison") or {}).get(claim_type, {"mode": "exact"})
    mode = rule.get("mode", "exact")
    values = [claim.get("value") for claim in group]
    if mode == "omega3_mg_components":
        parsed = [_parse_omega3_components(value) for value in values]
        if all(item is not None for item in parsed):
            # Milligrams mean nothing without the serving they are per. Values
            # were compared as bare numbers, so 360 mg per two softgels read as
            # a conflict with 180 mg per softgel (David's E4). Normalise to one
            # unit of a shared basis, or say the values cannot be compared.
            bases = [_serving_basis(value) for value in values]
            comparison = "policy comparison: EPA/DHA per serving unit"
            if any(basis is None for basis in bases) or len({unit for _, unit in bases}) > 1:
                return "incomparable", comparison + "; serving bases absent or incompatible"
            per_unit = [
                {c: item[c] / count for c in ("EPA", "DHA")}
                for item, (count, _) in zip(parsed, bases)
            ]
            tolerance = float(rule.get("absolute_tolerance_mg", 0))
            conflict = any(
                max(item[c] for item in per_unit) - min(item[c] for item in per_unit) > tolerance
                for c in ("EPA", "DHA")
            )
            return ("conflict" if conflict else "consistent"), (
                f"{comparison}, absolute tolerance {tolerance:g} mg"
            )
    normalised = {str(value).strip().casefold() for value in values}
    return ("conflict" if len(normalised) > 1 else "consistent"), "policy comparison: exact normalised value"


def check_conflicting_information(subject: dict) -> CheckResult:
    claims = subject.get("claims", [])
    by_type: dict[str, list[dict]] = {}
    for claim in claims:
        by_type.setdefault(claim["type"], []).append(claim)

    conflicts = []
    incomparable = []
    for claim_type, group in by_type.items():
        if len(group) < 2:
            continue
        status, comparison = _claim_values_conflict(claim_type, group)
        if status == "conflict":
            conflicts.append((claim_type, group, comparison))
        elif status == "incomparable":
            incomparable.append((claim_type, group, comparison))

    if incomparable and not conflicts:
        described = "; ".join(f"{claim_type} ({comparison})" for claim_type, _, comparison in incomparable)
        return CheckResult(
            "conflicting_information",
            "Conflicting information",
            INCOMPLETE,
            INCOMPLETE_SEVERITY,
            f"Issuers' values could not be compared on a common basis: {described}.",
            reason_codes=["claim_values_not_comparable"],
            evidence_consulted=[
                ref for _, group, _ in incomparable for c in group for ref in c.get("evidence_refs", [])
            ],
        )

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


# The checks run_all produces, in order, and the outcomes a check may report.
# Precedence validates against both before it will derive a posture (David's E4).
CHECK_IDS = (
    "identity",
    "standing",
    "seller_authority",
    "mandatory_evidence",
    "evidence_freshness",
    "claims_and_category",
    "conflicting_information",
)
KNOWN_OUTCOMES = frozenset({PASS, REVIEW, FAIL, INCOMPLETE})


def run_all(subject: dict | None, identify_result: dict, status_result: dict) -> list[CheckResult]:
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
        check_evidence_freshness(subject),
        check_claims_and_category(subject),
        check_conflicting_information(subject),
    ]
