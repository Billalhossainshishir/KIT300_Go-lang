#!/usr/bin/env python3
"""Capture the repository evidence David requested.

Run this from the final Git checkout after the release commit is created. The
script does not invent a commit identifier when Git metadata is absent.

One runner, pytest, is used for the release record, because the unittest route
omitted module-level pytest browser cases (David's T3). Test dependencies are
listed in requirements-dev.txt.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ASSESSMENT_EVIDENCE.json"
TEST_COMMAND = [sys.executable, "-m", "pytest", "backend/tests", "-q", "-rs"]
RECORDED_PACKAGES = (
    "fastapi", "uvicorn", "pydantic", "cryptography", "httpx",
    "langgraph", "langchain-core", "langchain-ollama", "pytest", "playwright",
)


def command(*args: str, env: dict | None = None) -> dict:
    try:
        run = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return {"available": False, "command": list(args), "error": f"{args[0]} not installed"}
    return {
        "available": True,
        "command": list(args),
        "returncode": run.returncode,
        # rstrip only: `git status --porcelain` lines start with a status column.
        "stdout": run.stdout.rstrip(),
        "stderr": run.stderr.strip(),
    }


def git_value(*args: str) -> str | None:
    """Output of a successful git command, or None if git could not answer.

    An empty output is a real answer. `git status --porcelain` prints nothing
    for a clean tree, and turning that into None recorded a clean checkout as
    null rather than true.
    """
    result = command("git", *args)
    if not result.get("available") or result.get("returncode") != 0:
        return None
    return result.get("stdout", "")


def test_totals(output: str) -> dict[str, int]:
    """Counts from pytest's final summary line, e.g. '497 passed, 2 skipped'."""
    summary = next(
        (line for line in reversed(output.splitlines()) if re.search(r"\d+ (passed|failed|error)", line)),
        "",
    )
    totals: dict[str, int] = {}
    for count, word in re.findall(r"(\d+) ([a-z]+)", summary):
        key = {"warning": "warnings", "error": "errors"}.get(word, word)
        totals[key] = int(count)
    return totals


def environment() -> dict:
    packages = {}
    for name in RECORDED_PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": packages,
    }


def main() -> int:
    commit = git_value("rev-parse", "HEAD")
    branch = git_value("rev-parse", "--abbrev-ref", "HEAD")
    commit_date = git_value("show", "-s", "--format=%cI", "HEAD")
    status = git_value("status", "--porcelain")

    test_env = dict(os.environ, PYTHONPATH="backend")
    test = command(*TEST_COMMAND, env=test_env)
    totals = test_totals(test.get("stdout", ""))

    record = {
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repository_visibility": "private — confirm access separately",
        "git_metadata_available": commit is not None,
        "assessed_branch": branch,
        "assessed_commit_sha": commit,
        "commit_date": commit_date,
        "working_tree_clean": (status == "") if status is not None else None,
        "working_tree_changes": status.splitlines() if status else [],
        "test_command": "PYTHONPATH=backend python -m pytest backend/tests -q -rs",
        "test_totals": totals,
        "test_result": test,
        "environment": environment(),
        "note": (
            "If assessed_commit_sha is null, this directory was not inside a Git checkout. "
            "Run the script again from the final private repository after committing the release. "
            "Skipped tests are listed in test_result.stdout; a skipped browser or live-model test "
            "is not evidence that it ran."
        ),
    }
    OUTPUT.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)
    return 0 if test.get("returncode") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
