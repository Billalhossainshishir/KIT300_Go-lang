"""Small, dependency-free helpers for durable local demo state.

The demo keeps mutable state in a per-machine data directory. JSON files are
written via a temporary sibling followed by ``os.replace`` so an interrupted
write cannot leave a half-written cart or agent profile file behind.

This is deliberately local-process durability, not a database replacement.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


class StoreCorrupt(RuntimeError):
    """Raised when local state exists but is not valid JSON/JSONL."""


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default() if callable(default) else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreCorrupt(f"Could not read local state from {path.name}: {exc}") from exc


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError as exc:
        raise StoreCorrupt(f"Could not write local state to {path.name}: {exc}") from exc
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass

def append_jsonl(path: Path, value: dict) -> None:
    """Append one JSONL record via copy-on-write replacement.

    The demo ledgers are small. Replacing the whole file is deliberately chosen
    over an in-place append so a process interruption cannot leave a half-written
    final JSON line that prevents the next client run from loading its history.
    Callers provide the in-process lock that serialises competing mutations.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    try:
        existing = path.read_bytes() if path.exists() else b""
        if existing and not existing.endswith(b"\n"):
            raise StoreCorrupt(f"Local ledger {path.name} has an incomplete final line.")

        temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with temp.open("wb") as handle:
                handle.write(existing)
                handle.write(line.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
    except StoreCorrupt:
        raise
    except OSError as exc:
        raise StoreCorrupt(f"Could not update local ledger {path.name}: {exc}") from exc

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise StoreCorrupt(
                        f"Local ledger {path.name} is invalid at line {number}: {exc.msg}"
                    ) from exc
                if not isinstance(value, dict):
                    raise StoreCorrupt(
                        f"Local ledger {path.name} contains a non-object at line {number}."
                    )
                rows.append(value)
    except OSError as exc:
        raise StoreCorrupt(f"Could not read local ledger {path.name}: {exc}") from exc
    return rows
