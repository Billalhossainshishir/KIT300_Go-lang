#!/usr/bin/env python3
"""Capture one reproducible RAMIFY release evidence record.

Run from the final Git checkout after creating the intended release commit. Git
metadata remains explicit/null if the exported directory is not a Git checkout.
Optional live-model evidence is recorded separately and never substituted for
the deterministic/full test result.
"""
from __future__ import annotations
import importlib.metadata as md
import json, os, statistics, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ASSESSMENT_EVIDENCE.json"


def command(*args: str, env=None) -> dict:
    try:
        run = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False, env=env)
    except FileNotFoundError:
        return {"available": False, "command": list(args), "error": f"{args[0]} not installed"}
    return {"available": True, "command": list(args), "returncode": run.returncode, "stdout": run.stdout.strip(), "stderr": run.stderr.strip()}


def git_result(*args: str) -> dict:
    return command("git", *args)


def git_text(*args: str) -> str | None:
    r = git_result(*args)
    if not r.get("available") or r.get("returncode") != 0: return None
    return r.get("stdout", "")


def package_version(name: str) -> str | None:
    try: return md.version(name)
    except md.PackageNotFoundError: return None


def benchmark() -> dict:
    sys.path.insert(0, str(ROOT / "backend"))
    with tempfile.TemporaryDirectory(prefix="ramify-release-benchmark-") as store:
        old = os.environ.get("RAMIFY_DATA_DIR"); os.environ["RAMIFY_DATA_DIR"] = store
        os.environ["RAMIFY_DISABLE_AGENT"] = "1"
        try:
            from ramify.engine import assess
            for _ in range(10): assess("ramify:demo:supp:apex-mg-glyc-120", "consumer_v1", context="guided_demo", persist_receipt=False)
            values=[]
            for _ in range(100):
                t=time.perf_counter_ns(); assess("ramify:demo:supp:apex-mg-glyc-120", "consumer_v1", context="guided_demo", persist_receipt=False); values.append((time.perf_counter_ns()-t)/1_000_000)
        finally:
            if old is None: os.environ.pop("RAMIFY_DATA_DIR", None)
            else: os.environ["RAMIFY_DATA_DIR"] = old
        ordered=sorted(values)
        p95=ordered[max(0, int(0.95*len(ordered))-1)]
        return {"path": "full engine call including receipt build/sign but excluding HTTP/browser", "runs": 100, "warmups": 10, "dataset": "synthetic v11.0.7 demo dataset", "median_ms": round(statistics.median(values),3), "p95_ms": round(p95,3), "max_ms": round(max(values),3)}


def main() -> int:
    commit = git_text("rev-parse", "HEAD")
    branch = git_text("rev-parse", "--abbrev-ref", "HEAD")
    commit_date = git_text("show", "-s", "--format=%cI", "HEAD")
    status_result = git_result("status", "--porcelain")
    git_available = status_result.get("available") and status_result.get("returncode") == 0 and commit is not None
    status = status_result.get("stdout", "") if git_available else None

    test = command(sys.executable, "-m", "pytest", "-q")
    live = command(sys.executable, "scripts/live_llm_smoke.py")
    record = {
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "app_version": (ROOT / "VERSION.txt").read_text().strip(),
        "repository_visibility": "private - confirm access separately",
        "git_metadata_available": bool(git_available),
        "assessed_branch": branch if git_available else None,
        "assessed_commit_sha": commit if git_available else None,
        "commit_date": commit_date if git_available else None,
        "working_tree_clean": (status == "") if git_available else None,
        "environment": {
            "python": sys.version.split()[0], "platform": sys.platform,
            "pytest": package_version("pytest"), "fastapi": package_version("fastapi"),
            "pydantic": package_version("pydantic"), "cryptography": package_version("cryptography"),
            "playwright": package_version("playwright"),
        },
        "full_test_command": f"{sys.executable} -m pytest -q",
        "full_test_result": test,
        "benchmark": benchmark(),
        "optional_live_model_evidence": {
            "command": f"{sys.executable} scripts/live_llm_smoke.py",
            "result": live,
            "interpretation": "return code 0 proves this run used the live local model and matched expected catalogue IDs; any other result is not live-model proof and does not invalidate deterministic RAMIFY",
        },
        "note": "If Git fields are null, rerun this script from the final private Git checkout after the release commit. Browser/live-model infrastructure skips must remain explicit and are not proof of execution.",
    }
    OUTPUT.write_text(json.dumps(record, indent=2) + "\n")
    print(OUTPUT)
    return 0 if test.get("returncode") == 0 else 1

if __name__ == "__main__": raise SystemExit(main())
