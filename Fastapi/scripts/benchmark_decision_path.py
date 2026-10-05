"""Measure the deterministic decision-to-checkout path against a stated boundary.

David's 1 October feedback and review R-06: the engine's displayed total sums
selected stages and leaves out receipt building, signing and storage, and the
100-run figure in the documents could not be reproduced from the scripts. This
measures one explicit boundary, reproducibly:

  journey = assess (all five primitives, actor policy, Action Gate selection,
            receipt build, Ed25519 seal, ledger write)
          + basket add (receipt re-verification, snapshot check, action record)
          + checkout (every line re-verified, order sealed and stored)

Local-model interpretation is outside this boundary on purpose; it is measured
separately by scripts/run_model_comparison.py. The HTTP layer is excluded too:
functions are called in-process, so the figures are the engine's cost, not a
network round trip.

Reported: the first (cold) journey on its own, then warm percentiles for each
stage and for the whole journey, then assessments under concurrent threads
(the basket is one shared store, so concurrency is measured on assessment
only). Hardware and software are recorded with the result.

    python scripts/benchmark_decision_path.py --runs 200 --threads 8
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["RAMIFY_DATA_DIR"] = tempfile.mkdtemp(prefix="ramify-benchmark-")
os.environ.pop("RAMIFY_DEMO_DETERMINISTIC", None)  # pinned clocks would fake the numbers

from ramify import engine  # noqa: E402
from ramify.action import cart  # noqa: E402

SUBJECT = "ramify:demo:supp:apex-mg-glyc-120"
ACTOR = "consumer_v1"
TARGET_MS = 200.0


def journey() -> dict[str, float]:
    timings = {}
    started = time.perf_counter()
    receipt = engine.assess(SUBJECT, ACTOR, context="purchase")["receipt"]
    timings["assess_and_seal"] = time.perf_counter() - started

    mark = time.perf_counter()
    cart.add(receipt["receipt_id"])
    timings["basket_add"] = time.perf_counter() - mark

    mark = time.perf_counter()
    cart.checkout()
    timings["checkout"] = time.perf_counter() - mark

    timings["journey"] = time.perf_counter() - started
    return {name: seconds * 1000 for name, seconds in timings.items()}


def summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def pct(p: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))], 3)

    return {
        "runs": len(ordered),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": pct(95),
        "p99_ms": pct(99),
        "max_ms": round(ordered[-1], 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--out", default=str(ROOT / "docs" / "evidence" / "benchmark.json"))
    args = parser.parse_args()

    cold = journey()
    warm: dict[str, list[float]] = {}
    for _ in range(args.runs):
        for name, ms in journey().items():
            warm.setdefault(name, []).append(ms)

    def timed_assess(_):
        started = time.perf_counter()
        engine.assess(SUBJECT, ACTOR, context="purchase")
        return (time.perf_counter() - started) * 1000

    wall = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        concurrent = list(pool.map(timed_assess, range(args.runs)))
    wall = time.perf_counter() - wall

    journey_p95 = summary(warm["journey"])["p95_ms"]
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "boundary": "assess + receipt build/sign/store + basket add + checkout; in-process; no model, no HTTP",
        "subject": SUBJECT,
        "actor": ACTOR,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
        },
        "cold_first_journey_ms": {k: round(v, 3) for k, v in cold.items()},
        "warm": {name: summary(values) for name, values in warm.items()},
        "concurrent_assessment": {
            "threads": args.threads,
            **summary(concurrent),
            "throughput_per_second": round(args.runs / wall, 1),
        },
        "target": {
            "journey_p95_under_ms": TARGET_MS,
            "met": journey_p95 < TARGET_MS,
            "note": "Local measurement on the host above; not a production capacity claim.",
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("cold_first_journey_ms", "warm", "concurrent_assessment", "target")}, indent=2))
    print(f"Recorded to {out}")
    return 0 if result["target"]["met"] else 1


if __name__ == "__main__":
    sys.exit(main())
