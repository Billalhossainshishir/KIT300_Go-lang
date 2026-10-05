"""Run two independently configured agents, on different local models, end to end.

David's 1 October feedback: compare_agent_adapters.py only reports which
adapters are available. This runs the experiment. Each agent has its own model
and its own RAMIFY policy. For every request it

  1. asks its model to pick a catalogue item from free text (timed separately),
  2. obtains RAMIFY's deterministic assessment and signed receipt,
  3. does what that receipt permits: checks out, raises a requisition,
     requests human review, or stops,

and the run records the model identity, request, interpretation, RAMIFY result
and resulting action. The model never sees or sets a posture, reason code or
action; it only chooses which product the words refer to.

Runs in an isolated temporary RAMIFY_DATA_DIR. Needs a local Ollama with the
named models; exits 2 with a clear message if they are missing.

    python scripts/run_model_comparison.py
    python scripts/run_model_comparison.py --agent "A=llama3.1:autonomous_buyer_v1" \
        --agent "B=mistral:procurement_v1" --out docs/evidence/model_comparison.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# A cold model load takes longer than the interactive demo's limit.
os.environ.setdefault("RAMIFY_LOCAL_MODEL_TIMEOUT", "120")
os.environ["RAMIFY_DATA_DIR"] = tempfile.mkdtemp(prefix="ramify-model-comparison-")

from fastapi.testclient import TestClient  # noqa: E402

from ramify.agent import interpreter  # noqa: E402
from ramify.agent.langgraph_adapter import DEFAULT_BASE_URL, LangGraphAdapter  # noqa: E402
from ramify.api.app import app  # noqa: E402

DEFAULT_AGENTS = ["A=llama3.1:autonomous_buyer_v1", "B=mistral:procurement_v1"]
REQUESTS = [
    "magnesium glycinate capsules, about 120",
    "vitamin C 1000mg tablets",
    "medium nitrile gloves",
    "ashwagandha root extract",
    "zinc picolinate",
]


def installed_models(base_url: str) -> dict[str, dict]:
    with urllib.request.urlopen(base_url.rstrip("/") + "/api/tags", timeout=5) as response:
        tags = json.load(response)
    return {m["name"].split(":latest")[0]: m for m in tags.get("models", [])}


def parse_agent(spec: str) -> dict:
    name, rest = spec.split("=", 1)
    model, actor_ref = rest.rsplit(":", 1)
    return {"name": name, "model": model, "actor_ref": actor_ref}


def act(client: TestClient, assessment: dict) -> dict:
    """Do what the signed receipt permits, and nothing else."""
    receipt = assessment["receipt"]
    permitted = set(receipt.get("permitted_actions", []))
    if assessment["requires_human"]:
        queue = client.get("/api/v0/review/queue").json()["open"]
        listed = any(item["receipt_id"] == receipt["receipt_id"] for item in queue)
        return {"action": "requested_human_review", "in_review_queue": listed}
    if permitted & {"purchase_autonomously", "add_to_mock_cart"}:
        added = client.post("/api/v0/cart/add", json={"receipt_ref": receipt["receipt_id"]})
        if added.status_code != 200:
            return {"action": "stopped", "detail": added.json().get("detail")}
        record = client.post("/api/v0/cart/checkout").json()["order"]
        report = client.post("/api/v0/receipt/verify", json=record).json()
        return {
            "action": "checked_out",
            "unattended": receipt.get("selected_action") == "purchase_autonomously",
            "order_id": record.get("order_id"),
            "order_verified": report.get("verified"),
        }
    if "create_mock_requisition" in permitted:
        created = client.post("/api/v0/requisition/create", json={"receipt_ref": receipt["receipt_id"]})
        body = created.json()
        record = body.get("requisition") or body
        return {"action": "requisition_created", "requisition_id": record.get("requisition_id")}
    return {"action": "stopped", "detail": f"decision {receipt['actor_decision']} permits no transaction"}


def run(agents: list[dict], requests: list[str]) -> dict:
    models = installed_models(DEFAULT_BASE_URL)
    missing = [a["model"] for a in agents if a["model"] not in models]
    if missing:
        print(f"Local Ollama does not have: {', '.join(missing)}. Pull them first.", file=sys.stderr)
        sys.exit(2)

    client = TestClient(app)
    catalogue = interpreter._candidate_products(None)
    runs = []
    for agent in agents:
        adapter = LangGraphAdapter(model=agent["model"])
        for text in requests:
            client.post("/api/v0/demo/cart/reset")
            started = time.perf_counter()
            try:
                reading = adapter.interpret(text, catalogue)
                interpretation = {
                    "identifier": reading.identifier,
                    "confidence": reading.confidence,
                    "note": reading.note,
                }
            except Exception as exc:  # recorded, not hidden
                interpretation = {"identifier": None, "error": f"{type(exc).__name__}: {exc}"}
            model_ms = round((time.perf_counter() - started) * 1000, 1)

            row = {
                "agent": agent["name"],
                "model": agent["model"],
                "model_digest": models[agent["model"]].get("digest"),
                "adapter": adapter.name,
                "actor_ref": agent["actor_ref"],
                "request": text,
                "interpretation": interpretation,
                "model_interpretation_ms": model_ms,
            }
            if not interpretation.get("identifier"):
                row["ramify"] = None
                row["outcome"] = {"action": "stopped", "detail": "the model did not identify a catalogue item"}
                runs.append(row)
                print(f"{agent['name']} [{agent['model']}] {text!r} -> no item -> stopped")
                continue

            started = time.perf_counter()
            assessment = client.post("/api/v0/assess", json={
                "identifier": interpretation["identifier"], "actor_ref": agent["actor_ref"],
                "quantity": 1, "context": "purchase",
            }).json()
            row["ramify"] = {
                "subject_ref": assessment.get("subject_ref"),
                "objective_posture": assessment.get("objective_posture"),
                "actor_decision": assessment.get("actor_decision"),
                "selected_action": assessment.get("selected_action"),
                "reason_codes": assessment.get("reason_codes"),
                "receipt_id": assessment.get("receipt_ref"),
                "actor_profile_digest": assessment.get("receipt", {}).get("actor_profile_digest"),
            }
            row["outcome"] = act(client, assessment)
            row["deterministic_path_ms"] = round((time.perf_counter() - started) * 1000, 1)
            runs.append(row)
            print(f"{agent['name']} [{agent['model']}] {text!r} -> "
                  f"{interpretation['identifier']} -> {row['ramify']['actor_decision']} -> "
                  f"{row['outcome']['action']}")

    return {
        "experiment": "two independently configured agents on different local models",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "ollama": DEFAULT_BASE_URL,
        "agents": agents,
        "boundary": (
            "Models choose a catalogue item only. RAMIFY's assessment, actor policy, Action Gate "
            "and signing are deterministic and identical for both agents. Interpretation time "
            "is reported separately from the deterministic path."
        ),
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--agent", action="append", help="NAME=model:actor_ref (repeatable)")
    parser.add_argument("--out", default=str(ROOT / "docs" / "evidence" / "model_comparison.json"))
    args = parser.parse_args()
    agents = [parse_agent(spec) for spec in (args.agent or DEFAULT_AGENTS)]
    if len({a["model"] for a in agents}) < 2:
        parser.error("use at least two different models")
    result = run(agents, REQUESTS)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {len(result['runs'])} runs to {out}")
    unverified = [
        r for r in result["runs"]
        if r["outcome"].get("action") == "checked_out" and not r["outcome"].get("order_verified")
    ]
    return 1 if unverified else 0


if __name__ == "__main__":
    sys.exit(main())
