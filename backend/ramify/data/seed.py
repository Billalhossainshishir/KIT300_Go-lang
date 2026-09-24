"""The demonstration dataset and the Demo Policy Pack.

Read once at import and treated as immutable. Dates are evaluated against the
snapshot date carried in the file, not the wall clock, so a scenario that
returns `allow_with_warning` today still returns it next year.

Evidence signatures sit in a generated file because they are produced at seed
time with issuer keys that do not ship.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
SEED_PATH = DATA_DIR / "demo_seed.json"
POLICY_PACK_PATH = DATA_DIR / "policy_pack_demo_v1.json"
GENERATED_DIR = DATA_DIR / "generated"
EVIDENCE_SIGNATURES_PATH = GENERATED_DIR / "evidence_signatures.json"


def deterministic_mode() -> bool:
    """Parity testing only — pins the clock, receipt id and stage timings.

    Amendment v0.4.1 item 3. Live receipts carry live values, so two machines
    cannot otherwise produce identical hashes.
    """
    return os.environ.get("RAMIFY_DEMO_DETERMINISTIC") == "1"


@lru_cache(maxsize=1)
def seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def policy_pack() -> dict:
    return json.loads(POLICY_PACK_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def evidence_signatures() -> dict[str, dict[str, str]]:
    if not EVIDENCE_SIGNATURES_PATH.exists():
        return {}
    return json.loads(EVIDENCE_SIGNATURES_PATH.read_text(encoding="utf-8"))


def parse_timestamp(value: str) -> datetime:
    """Parse RFC3339, tolerating the nanosecond form Python will not."""
    text = value.replace("Z", "+00:00")
    if "." in text:
        head, _, tail = text.partition(".")
        fraction, sign, offset = (
            tail.partition("+") if "+" in tail else tail.partition("-")
        )
        text = f"{head}.{fraction[:6]}{sign}{offset}"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def snapshot_date() -> datetime:
    """The fixed date every freshness comparison runs against."""
    return parse_timestamp(seed()["meta"]["snapshot_date"])


def snapshot_id() -> str:
    return seed()["meta"]["snapshot_id"]


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def policy_digest() -> str:
    """Digest of the exact policy pack bytes evaluated by this build."""
    return _sha256_file(POLICY_PACK_PATH)


def dataset_digest() -> str:
    """Digest of the exact synthetic dataset bytes evaluated by this build."""
    return _sha256_file(SEED_PATH)


def subjects() -> dict:
    return seed()["subjects"]


def subject(ref: str) -> dict | None:
    return seed()["subjects"].get(ref)


def status_for(ref: str) -> dict | None:
    return seed()["statuses"].get(ref)


def evidence(ref: str) -> dict | None:
    record = seed()["evidence"].get(ref)
    if record is None:
        return None
    signed = dict(record)
    signed.update(evidence_signatures().get(ref, {}))
    return signed


def seller(ref: str) -> dict | None:
    return seed()["sellers"].get(ref)


def issuer(ref: str) -> dict | None:
    return seed()["issuers"].get(ref)


def category(name: str) -> dict | None:
    return seed()["categories"].get(name)


def price_cents(subject_ref: str) -> int | None:
    """Listed price in integer cents — a float cannot enter a signed receipt."""
    return seed()["listings"]["prices_cents"].get(subject_ref)


def actor_profile(ref: str) -> dict | None:
    return seed()["actor_profiles"].get(ref)


def actor_profiles() -> dict:
    return seed()["actor_profiles"]


def scenarios() -> list[dict]:
    return seed()["scenarios"]
