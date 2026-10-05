"""Append-only receipt and action stores.

Human-review decisions append linked successor receipts rather than rewriting
original machine decisions. Mutable files live in the per-machine RAMIFY data
store and are guarded by an in-process re-entrant lock so simultaneous browser
requests cannot interleave ledger updates.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock

from ramify.crypto import keys
from ramify.storage import append_jsonl, read_jsonl

LEDGER_NAME = "receipts.jsonl"
ACTION_LOG_NAME = "actions.jsonl"
AWAITING_REVIEW = ("hold", "escalate")

_LOCK = RLock()


def ledger_path() -> Path:
    directory = keys.local_data_store()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / LEDGER_NAME


def action_log_path() -> Path:
    directory = keys.local_data_store()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / ACTION_LOG_NAME


def append(receipt: dict) -> dict:
    with _LOCK:
        append_jsonl(ledger_path(), receipt)
    return receipt


def all_receipts() -> list[dict]:
    with _LOCK:
        return read_jsonl(ledger_path())


def get(receipt_id: str) -> dict | None:
    if not receipt_id:
        return None
    for receipt in reversed(all_receipts()):
        if receipt.get("receipt_id") == receipt_id:
            return receipt
    return None


def recent(limit: int = 20) -> list[dict]:
    limit = max(1, int(limit))
    return all_receipts()[-limit:][::-1]


def superseding_chain(receipt_id: str) -> list[dict]:
    """Every receipt that directly supersedes the given one, oldest first."""
    return [r for r in all_receipts() if r.get("supersedes_receipt") == receipt_id]


class SuccessorExists(RuntimeError):
    """Raised when two requests try to answer the same review."""


def has_successor(receipt_id: str) -> bool:
    return any(r.get("supersedes_receipt") == receipt_id for r in all_receipts())


def is_review_answered(receipt: dict) -> bool:
    """True when this receipt is already part of a settled review chain.

    A successor keeps the original's ``actor_decision`` on purpose, so that the
    machine verdict is never rewritten by a person. That also leaves it looking
    reviewable: same held decision, no successor of its own, a fresh validity
    window. Reviewing it again would mint a second authority from one person's
    single decision, and the chain could be extended without limit.

    A chain is therefore terminal at both ends. A receipt carrying a human
    answer is one, and so is any receipt that supersedes another.
    """
    return bool(receipt.get("human_review")) or bool(receipt.get("supersedes_receipt"))


def append_successor(original_id: str, receipt: dict) -> dict:
    """Append exactly one direct successor for a receipt, atomically in-process."""
    with _LOCK:
        rows = read_jsonl(ledger_path())
        if any(row.get("supersedes_receipt") == original_id for row in rows):
            raise SuccessorExists(original_id)
        append_jsonl(ledger_path(), receipt)
    return receipt


def review_queue(limit: int = 50) -> list[dict]:
    """Purchase receipts that stopped for a person and are still unanswered."""
    receipts = all_receipts()
    answered = {r["supersedes_receipt"] for r in receipts if r.get("supersedes_receipt")}
    open_items = [
        r
        for r in receipts
        if r.get("actor_decision") in AWAITING_REVIEW
        and r.get("assessment_context") == "purchase"
        and r.get("receipt_id") not in answered
        and not r.get("human_review")
    ]
    return open_items[-max(1, int(limit)):][::-1]


def resolved_reviews(limit: int = 50) -> list[dict]:
    answered = [r for r in all_receipts() if r.get("human_review")]
    return answered[-max(1, int(limit)):][::-1]


def _event_hash(event: dict) -> str:
    payload = {key: value for key, value in event.items() if key != "event_hash"}
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _all_actions_chronological() -> list[dict]:
    return read_jsonl(action_log_path())


def _append_linked_action(rows: list[dict], event: dict) -> dict:
    linked = dict(event)
    linked["event_sequence"] = len(rows) + 1
    linked["previous_event_hash"] = rows[-1].get("event_hash") if rows else "GENESIS"
    linked["event_hash"] = _event_hash(linked)
    append_jsonl(action_log_path(), linked)
    return linked


def record_action(event: dict) -> dict:
    """Append a hash-linked Action Gate event atomically within this process."""
    with _LOCK:
        rows = _all_actions_chronological()
        return _append_linked_action(rows, event)


def record_action_once(event: dict) -> tuple[dict, bool]:
    """Append one receipt/action pair at most once, atomically in-process.

    UI clicks and transaction endpoints can race on a presentation laptop. The
    uniqueness check therefore belongs inside the same ledger lock as the
    append rather than in a separate read followed by a write.
    """
    receipt_ref = event.get("receipt_ref")
    action = event.get("action")
    with _LOCK:
        rows = _all_actions_chronological()
        existing = next(
            (
                row
                for row in reversed(rows)
                if row.get("receipt_ref") == receipt_ref and row.get("action") == action
            ),
            None,
        )
        if existing is not None:
            return existing, False
        return _append_linked_action(rows, event), True


def actions(limit: int = 50) -> list[dict]:
    with _LOCK:
        rows = _all_actions_chronological()
    return rows[-max(1, int(limit)):][::-1]


def actions_for(receipt_id: str) -> list[dict]:
    """Every action recorded against a receipt, newest first, however old.

    This used to look only at the latest 1,000 events, so a receipt's older
    actions silently dropped out of its history (David's M1).
    """
    with _LOCK:
        rows = _all_actions_chronological()
    return [e for e in reversed(rows) if e.get("receipt_ref") == receipt_id]


def verify_action_ledger() -> dict:
    """Recompute the append-only action chain without trusting stored hashes."""
    with _LOCK:
        rows = _all_actions_chronological()
        # One read of the receipt ledger for the whole run. Looking each linked
        # receipt up separately re-read the entire file once per action (M1).
        receipts_by_id = {r.get("receipt_id"): r for r in all_receipts()}
    expected_previous = "GENESIS"
    problems: list[dict] = []
    for index, row in enumerate(rows, start=1):
        if row.get("event_sequence") != index:
            problems.append({"sequence": index, "problem": "event_sequence mismatch"})
        if row.get("previous_event_hash") != expected_previous:
            problems.append({"sequence": index, "problem": "previous_event_hash mismatch"})
        recomputed = _event_hash(row)
        if row.get("event_hash") != recomputed:
            problems.append({"sequence": index, "problem": "event_hash mismatch"})

        receipt_ref = row.get("receipt_ref")
        receipt_hash = row.get("receipt_hash")
        if receipt_ref:
            receipt = receipts_by_id.get(receipt_ref)
            if receipt is None:
                problems.append({"sequence": index, "problem": "receipt_ref missing from receipt ledger"})
            else:
                if receipt.get("payload_hash") != receipt_hash:
                    problems.append({"sequence": index, "problem": "receipt_hash does not match linked receipt"})
                from ramify.crypto.sign import verify_receipt
                report = verify_receipt(receipt)
                if not report.get("integrity_verified"):
                    problems.append({"sequence": index, "problem": "linked receipt integrity does not verify"})
        else:
            problems.append({"sequence": index, "problem": "event has no receipt_ref"})

        expected_previous = row.get("event_hash", "")
    return {
        "total": len(rows),
        "valid": not problems,
        "problems": problems,
        "head_hash": expected_previous if rows else "GENESIS",
        "note": "SHA-256 hash-linked local demonstration ledger with receipt-link verification; not a distributed immutable log.",
    }
