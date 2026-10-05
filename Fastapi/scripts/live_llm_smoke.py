"""Small presentation-laptop check for the real LangGraph + Ollama path.

Run after `ollama pull llama3.1`. This intentionally fails if a request falls
back to the deterministic matcher, so the presenter knows whether the live
model is genuinely participating before showing it to a client.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from ramify.agent import interpreter

# Each request with the product it should identify. Participation alone passed
# even when every answer was NO MATCH (David's R1), so correctness is checked
# separately and either failure fails the run.
REQUESTS = [
    ("I need magnesium glycinate capsules.", "ramify:demo:supp:apex-mg-glyc-120"),
    ("Show me the Greenline ashwagandha product.", "ramify:demo:supp:greenline-ashw-ksm66-90"),
    ("Find the Northbeam vitamin C supplement.", "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A"),
    ("I need the N95 mask in the catalogue.", "ramify:demo:ppe:covelane-n95-resp-b2026-01-B"),
    ("I want omega-3 fish oil.", "ramify:demo:supp:tidalpoint-omega3-1000-b2025-12-D"),
]


def main() -> int:
    status = interpreter.status()
    print(f"Framework: {status.get('framework')} | Provider: {status.get('provider')} | Model: {status.get('model')}")
    if not status.get("local_model_available"):
        print("LIVE LOCAL AI NOT READY:", status.get("detail") or status.get("presentation_detail"))
        return 2

    not_live = 0
    wrong = 0
    for index, (request, expected) in enumerate(REQUESTS, 1):
        reading = interpreter.interpret(request, mode="local_llm")
        live = str(reading.get("source", "")).startswith("langgraph+ollama:")
        identifier = reading.get("identifier")
        correct = identifier == expected
        latency = reading.get("latency_ms")
        print(f"{index}. {request}\n   -> {identifier or 'NO MATCH'} | {latency} ms | {reading.get('source')}"
              f" | {'correct' if correct else 'expected ' + expected}")
        not_live += not live
        wrong += not correct

    if not_live:
        print(f"FAIL participation: {not_live} request(s) did not use the live local LLM path.")
    if wrong:
        print(f"FAIL correctness: {wrong} request(s) identified the wrong product or none.")
    if not_live or wrong:
        return 1
    print(f"PASS: all {len(REQUESTS)} requests used the live local model and identified the expected product.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
