"""Acceptance regressions for David Male's remaining 21 September 2026 feedback.

The P1 transaction/evidence fixes live in test_david_feedback_21sep_p1.py.
This module covers the remaining E3/E4, I1, L1/L2, M1, T2/T3, U1/U2,
R1/R2 behaviours that can be verified in an automated local test.

Client acceptance itself is deliberately not asserted here; that remains a
separate human/client step in the coverage matrix.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ramify import engine
from ramify.agent import explain
from ramify.agent.pydanticai_adapter import PydanticAIAdapter, _validated_model_and_base
from ramify.api.app import app
from ramify.crypto.sign import verify_receipt
from ramify.data import seed
from ramify.policy import actor as actor_policy
from ramify.ratify import checks, precedence, verify as ratify_verify
from ramify.receipt import store
from ramify.storage import append_jsonl

ROOT = Path(__file__).resolve().parents[2]
client = TestClient(app)
APEX = "ramify:demo:supp:apex-mg-glyc-120"
RECALL = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"


class _TempStore:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"RAMIFY_DATA_DIR": self.temp.name, "RAMIFY_DISABLE_AGENT": "1"})
        self.env.start()
        return Path(self.temp.name)

    def __exit__(self, exc_type, exc, tb):
        self.env.stop()
        self.temp.cleanup()


def test_e3_claim_without_evidence_cannot_be_accepted():
    subject = copy.deepcopy(seed.subject(APEX))
    subject["claims"][0]["evidence_refs"] = []
    results = ratify_verify.claim_results(subject)
    first = next(row for row in results if row["claim_ref"] == subject["claims"][0]["ref"])
    assert first["verdict"] == "rejected"
    assert "claim_evidence_missing" in first["reason_codes"]

    aggregate = checks.check_claims_and_category(subject)
    assert aggregate.outcome == checks.FAIL
    assert aggregate.severity == checks.HARD_STOP
    assert "claim_evidence_binding_invalid" in aggregate.reason_codes


def test_e4_invalid_or_incomplete_check_set_fails_closed():
    outcome = precedence.evaluate([], "no_active_recall", require_complete=True)
    assert outcome.posture == precedence.ESCALATE
    assert "ratify_check_set_invalid" in outcome.reason_codes

    valid = checks.CheckResult("identity", "Identity", checks.PASS, checks.INFORMATIONAL, "ok")
    broken = copy.deepcopy(valid)
    broken.outcome = "mystery"
    outcome = precedence.evaluate([broken], "no_active_recall", require_complete=True)
    assert outcome.posture == precedence.ESCALATE
    assert "ratify_check_set_invalid" in outcome.reason_codes


def test_e4_omega3_values_are_normalised_by_compatible_serving_basis():
    group = [
        {"value": "EPA 300 mg DHA 200 mg per 2 capsules"},
        {"value": "EPA 150 mg DHA 100 mg per 1 capsule"},
    ]
    conflict, detail = checks._claim_values_conflict("ingredient_claim", group)
    assert conflict is False
    assert "serving basis" in detail

    incompatible = [
        {"value": "EPA 300 mg DHA 200 mg per 2 capsules"},
        {"value": "EPA 150 mg DHA 100 mg per 1 serving"},
    ]
    conflict, detail = checks._claim_values_conflict("ingredient_claim", incompatible)
    assert conflict is True
    assert "incompatible" in detail


@pytest.mark.parametrize("quantity", [True, "2", 1.0, 0, -1, 1001])
def test_i1_api_quantity_semantics_are_strict(quantity):
    response = client.post("/api/v0/assess", json={"identifier": APEX, "quantity": quantity})
    assert response.status_code == 422


@pytest.mark.parametrize("quantity", [True, "2", 1.0, 0, -1, 1001])
def test_i1_domain_quantity_semantics_are_strict(quantity):
    with pytest.raises(ValueError):
        engine.assess(APEX, quantity=quantity, persist_receipt=False)


def test_i1_missing_price_is_not_described_as_over_budget():
    with patch("ramify.engine.seed.price_cents", return_value=None):
        result = engine.assess(APEX, "budget_guard_v1", persist_receipt=False)
    assert result["actor_decision"] == "hold"
    assert "line_total_unavailable_for_agent_budget" in result["reason_codes"]
    assert "line_total_exceeds_agent_budget" not in result["reason_codes"]
    condition = next(c for c in result["conditions_evaluated"] if c["id"] == "price_unavailable_for_budget")
    assert "no price" in condition["detail"].lower()


def test_l1_external_pydanticai_endpoint_is_rejected():
    with patch.dict(os.environ, {"RAMIFY_OLLAMA_BASE_URL": "https://example.com:11434"}, clear=False):
        with pytest.raises(ValueError):
            _validated_model_and_base()


def test_l1_validated_loopback_endpoint_reaches_provider_constructor():
    captured = {}

    class FakeProvider:
        def __init__(self, *, base_url, api_key):
            captured["base_url"] = base_url
            captured["api_key"] = api_key

    class FakeModel:
        def __init__(self, model_name, *, provider):
            captured["model_name"] = model_name
            captured["provider"] = provider

    class FakeAgent:
        def __init__(self, model, system_prompt):
            captured["agent_model"] = model
            captured["system_prompt"] = system_prompt

    pkg = types.ModuleType("pydantic_ai")
    pkg.Agent = FakeAgent
    models = types.ModuleType("pydantic_ai.models")
    openai_models = types.ModuleType("pydantic_ai.models.openai")
    openai_models.OpenAIModel = FakeModel
    providers = types.ModuleType("pydantic_ai.providers")
    openai_providers = types.ModuleType("pydantic_ai.providers.openai")
    openai_providers.OpenAIProvider = FakeProvider
    fake_modules = {
        "pydantic_ai": pkg,
        "pydantic_ai.models": models,
        "pydantic_ai.models.openai": openai_models,
        "pydantic_ai.providers": providers,
        "pydantic_ai.providers.openai": openai_providers,
    }
    with patch.dict(sys.modules, fake_modules), patch.dict(
        os.environ,
        {"RAMIFY_PYDANTICAI_MODEL": "ollama:llama3.1", "RAMIFY_OLLAMA_BASE_URL": "http://127.0.0.1:11434"},
        clear=False,
    ):
        adapter = PydanticAIAdapter()
        adapter._ensure_agent()
    assert captured["base_url"] == "http://127.0.0.1:11434/v1"
    assert captured["model_name"] == "llama3.1"


def test_l1_non_object_model_response_falls_back_without_authority():
    class FakeRun:
        output = "[]"
    class FakeAgent:
        def run_sync(self, prompt):
            return FakeRun()
    adapter = PydanticAIAdapter()
    adapter._agent = FakeAgent()
    result = adapter.interpret("anything", [{"subject_ref": APEX}])
    assert result.identifier is None
    assert result.confidence == 0.0


def test_l2_contradictory_model_approval_is_rejected_for_blocked_receipt():
    with _TempStore():
        receipt = engine.assess(RECALL, "consumer_v1", context="purchase")["receipt"]

        class FakeAdapter:
            name = "fake-local-model"
            def explain(self, receipt):
                return "This product is safe to buy and may proceed."

        with patch("ramify.agent.explain._configured_adapter", return_value=FakeAdapter()):
            result = explain.explain_receipt(receipt)
        assert result["model_text_accepted"] is False
        assert result["text"] == result["authoritative_summary"]
        assert "must not proceed" in result["text"].lower()


def test_u1_authentic_expired_receipt_remains_integrity_verified():
    with _TempStore():
        receipt = engine.assess(APEX, "consumer_v1", context="purchase")["receipt"]
        expiry = datetime.fromisoformat(receipt["expires_at"].replace("Z", "+00:00"))
        report = verify_receipt(receipt, now=expiry + timedelta(seconds=1))
    assert report["integrity_verified"] is True
    assert report["purchase_authority_valid"] is False
    assert report["verified"] is False


def test_u1_shared_ui_names_integrity_and_purchase_authority_separately():
    script = (ROOT / "frontend" / "scripts" / "shell.js").read_text(encoding="utf-8")
    assert "Receipt integrity:" in script
    assert "Purchase authority:" in script
    assert "report.integrity_verified ?? report.verified" in script


def test_u2_evidence_tamper_demo_never_changes_shared_artefact():
    record = seed.evidence("ev:apex:coa")
    path = seed.DATA_DIR / record["storage_path"]
    before = path.read_bytes()
    response = client.post("/api/v0/demo/evidence-tamper", json={"subject_ref": APEX})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["shared_artefact_modified"] is False
    assert path.read_bytes() == before


def test_u2_checkout_demo_uses_dedicated_cart_and_keeps_normal_basket():
    with _TempStore():
        normal = engine.assess(APEX, "consumer_v1", context="purchase")["receipt"]
        from ramify.action import cart
        cart.add(normal["receipt_id"])
        before = cart.contents()
        response = client.post("/api/v0/demo/checkout-proof")
        assert response.status_code == 200, response.text
        assert response.json()["normal_cart_untouched"] is True
        after = cart.contents()
        assert [x["receipt_ref"] for x in after["lines"]] == [x["receipt_ref"] for x in before["lines"]]


def test_u2_absent_status_is_a_separate_unknown_case():
    response = client.get("/api/v0/demo/absent-status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["standing"] == "unknown"
    assert payload["check"]["outcome"] == checks.INCOMPLETE
    assert "status_unknown" in payload["reason_codes"]


def test_m1_engine_reports_named_timing_boundaries():
    with _TempStore():
        result = engine.assess(APEX, "consumer_v1", context="guided_demo", persist_receipt=False)
    timing = result["runtime_timing_ms"]
    assert set(("deterministic_evaluation", "receipt_build_and_sign", "receipt_persistence", "full_engine_call")) <= set(timing)
    assert "HTTP/network/browser" in timing["scope_note"]


def test_m1_actions_for_has_no_1000_event_cutoff():
    with _TempStore():
        path = store.action_log_path()
        for index in range(1005):
            append_jsonl(path, {"receipt_ref": "target", "event_sequence": index + 1})
        assert len(store.actions_for("target")) == 1005


def test_t2_browser_acceptance_file_uses_visible_controls_for_core_journeys():
    source = (ROOT / "backend" / "tests" / "test_browser_e2e_optional.py").read_text(encoding="utf-8")
    for token in ("#continue-ramify", "#journey-next", "#add-to-cart", "#checkout", "[data-decide=\"overridden\"]"):
        assert token in source
    assert "test_browser_consumer_can_complete_authorised_checkout_through_visible_ui" in source
    assert "test_browser_procurement_human_review_creates_requisition_through_visible_ui" in source


def _load_script_module(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_t3_git_text_preserves_successful_empty_status():
    module = _load_script_module("capture_release_evidence.py", "capture_release_evidence_test")
    with patch.object(module, "git_result", return_value={"available": True, "returncode": 0, "stdout": "", "stderr": ""}):
        assert module.git_text("status", "--porcelain") == ""


def test_r1_forced_failed_demo_proof_changes_exit_code():
    module = _load_script_module("david_live_verification_demo.py", "david_demo_test")
    module.FAILURES = 0
    module.result("forced failure", False)
    assert module.FAILURES == 1


def test_r1_llm_smoke_requires_expected_identifiers_not_just_model_participation():
    module = _load_script_module("live_llm_smoke.py", "llm_smoke_test")
    expected = [row[1] for row in module.REQUESTS]
    assert len(expected) == 5 and len(set(expected)) == 5

    with patch.object(module.interpreter, "status", return_value={"framework": "LangGraph", "provider": "Ollama", "model": "x", "local_model_available": True}), patch.object(
        module.interpreter,
        "interpret",
        return_value={"source": "langgraph+ollama:x", "identifier": None, "latency_ms": 1},
    ):
        assert module.main() == 1


def test_r2_quick_proof_pack_manifest_detects_missing_expected_file_and_malformed_shape():
    response = client.get("/api/v0/proof-pack")
    assert response.status_code == 200
    import io, zipfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            zf.extractall(root)
        verifier = root / "verify_receipts.py"
        first = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["expected_receipts"][0]["filename"]
        target = root / first
        target.unlink()
        missing = subprocess.run([sys.executable, str(verifier)], cwd=root, text=True, capture_output=True)
        assert missing.returncode != 0
        assert "missing expected receipt" in missing.stdout.lower()

        # Re-extract then replace one declared receipt with a non-object JSON value,
        # updating the manifest digest so shape validation, not digest mismatch, is exercised.
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            zf.extractall(root)
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        row = manifest["expected_receipts"][0]
        target = root / row["filename"]
        target.write_text("[]\n", encoding="utf-8")
        import hashlib
        row["sha256"] = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        malformed = subprocess.run([sys.executable, str(verifier)], cwd=root, text=True, capture_output=True)
        assert malformed.returncode != 0
        assert "receipt must be a json object" in malformed.stdout.lower()
