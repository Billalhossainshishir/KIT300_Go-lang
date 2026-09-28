"""Optional presentation-laptop correctness check for LangGraph + Ollama.

This is separate evidence. Its absence never prevents deterministic RAMIFY from
running, and a skip/failure must not be reported as proof that live inference
was exercised.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from ramify.agent import interpreter

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
    failures = 0
    for index, (request, expected) in enumerate(REQUESTS, 1):
        reading = interpreter.interpret(request, mode="local_llm")
        live = str(reading.get("source", "")).startswith("langgraph+ollama:")
        actual = reading.get("identifier")
        ok = live and actual == expected
        print(f"{index}. {'PASS' if ok else 'FAIL'} {request}\n   expected {expected}\n   actual   {actual or 'NO MATCH'} | {reading.get('latency_ms')} ms | {reading.get('source')}")
        failures += 0 if ok else 1
    if failures:
        print(f"FAIL: {failures} request(s) did not use live local inference with the expected catalogue match.")
        return 1
    print("PASS: all five requests used LangGraph + Ollama and identified the expected local catalogue product.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
