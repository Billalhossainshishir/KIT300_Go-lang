"""Safe request interpretation for the client-facing demo.

Exact local identifiers are resolved deterministically. Loose natural language
may be interpreted by the local LangGraph + Ollama layer when it is ready; if
that layer is missing or slow, the fixed-catalogue deterministic matcher remains
available. Neither path can supply a trust posture, reason code or action.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

from ramify.agent import tools
from ramify.agent.protocol import Interpretation
from ramify.resolve import primitives

LOCAL_MODEL_CALL_TIMEOUT_SECONDS = float(os.environ.get("RAMIFY_LOCAL_MODEL_TIMEOUT", "5"))
_MODEL_CALL_SLOT = threading.Lock()
_MODEL_STATE_LOCK = threading.Lock()
_MODEL_RUNTIME = {"state": "not_tested", "detail": "Live local AI has not been used yet.", "at": 0.0}


def _set_model_runtime(state: str, detail: str) -> None:
    with _MODEL_STATE_LOCK:
        _MODEL_RUNTIME.update({"state": state, "detail": detail, "at": time.time()})


def _model_runtime_snapshot() -> dict:
    with _MODEL_STATE_LOCK:
        return dict(_MODEL_RUNTIME)


def _normalise(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1
        and token not in {
            "buy", "get", "please", "from", "the", "a", "an", "for", "me", "want", "check",
            "i", "need", "show", "find", "in", "catalogue", "catalog", "product", "item", "looking",
            "give", "some", "this", "that", "my", "to", "of", "with",
        }
    ]


def _catalogue_score(query: str, product: dict[str, Any]) -> int:
    terms = _normalise(query)
    if not terms:
        return 0
    haystack = " ".join(
        str(product.get(key, ""))
        for key in ("name", "brand", "category", "gtin", "subject_ref", "seller_name")
    ).lower()
    name = str(product.get("name", "")).lower()
    score = 0
    for term in terms:
        if term in haystack:
            score += 3 if term in name else 1
    return score


def _candidate_products(candidate_refs: list[str] | None) -> list[dict[str, Any]]:
    products = tools.list_products()
    if not candidate_refs:
        return products
    allowed = {str(ref) for ref in candidate_refs}
    return [product for product in products if product.get("subject_ref") in allowed]


def deterministic_interpret(
    request_text: str,
    actor_ref: str = "consumer_v1",
    candidate_refs: list[str] | None = None,
) -> dict:
    """Interpret without a model, using only the fixed local catalogue."""
    allowed = {p["subject_ref"] for p in _candidate_products(candidate_refs)}
    exact = primitives.identify(request_text)
    if exact.get("resolved") and (not candidate_refs or exact["subject_ref"] in allowed):
        return {
            "identifier": exact["subject_ref"],
            "actor_ref": actor_ref,
            "confidence": 1.0,
            "source": "exact_identifier",
            "note": "Matched an exact local identifier.",
            "candidates": [exact["subject_ref"]],
            "authoritative": False,
            "boundary": "Interpretation only. The deterministic engine decides trust.",
        }

    products = _candidate_products(candidate_refs)
    if candidate_refs and not products:
        return {
            "identifier": None,
            "actor_ref": actor_ref,
            "confidence": 0.0,
            "source": "deterministic_catalogue_search",
            "note": "The selected catalogue item is no longer available in this local dataset.",
            "candidates": [],
            "authoritative": False,
            "boundary": "Interpretation only. The deterministic engine decides trust.",
        }

    ranked = sorted(
        [(_catalogue_score(request_text, product), product) for product in products],
        key=lambda row: (-row[0], row[1]["name"]),
    )
    ranked = [row for row in ranked if row[0] > 0]
    if not ranked:
        return {
            "identifier": None,
            "actor_ref": actor_ref,
            "confidence": 0.0,
            "source": "deterministic_catalogue_search",
            "note": "No product in the local catalogue clearly matched that request.",
            "candidates": [],
            "authoritative": False,
            "boundary": "Interpretation only. The deterministic engine decides trust.",
        }

    top_score = ranked[0][0]
    best = [product for score, product in ranked if score == top_score]
    total_terms = max(1, len(_normalise(request_text)))
    confidence = min(0.98, 0.55 + (top_score / (total_terms * 3)) * 0.43)

    # Equal top scores are genuinely ambiguous. Choosing alphabetically would
    # look deterministic while still being a guess, so ask the user to choose.
    if len(best) > 1:
        return {
            "identifier": None,
            "actor_ref": actor_ref,
            "confidence": min(round(confidence, 2), 0.72),
            "source": "deterministic_catalogue_search",
            "note": "Several catalogue products match equally well. Choose a product card to continue.",
            "candidates": [product["subject_ref"] for product in best[:5]],
            "authoritative": False,
            "boundary": "Interpretation only. The deterministic engine decides trust.",
        }

    chosen = best[0]
    return {
        "identifier": chosen["subject_ref"],
        "actor_ref": actor_ref,
        "confidence": round(confidence, 2),
        "source": "deterministic_catalogue_search",
        "note": f"Matched {chosen['name']} from the fixed local catalogue.",
        "candidates": [chosen["subject_ref"]],
        "authoritative": False,
        "boundary": "Interpretation only. The deterministic engine decides trust.",
    }


def _try_local_model(
    request_text: str,
    actor_ref: str,
    candidate_refs: list[str] | None = None,
) -> dict | None:
    if os.environ.get("RAMIFY_DISABLE_AGENT") == "1":
        _set_model_runtime("disabled", "Local AI was intentionally disabled; safe deterministic mode is active.")
        return None
    if not _MODEL_CALL_SLOT.acquire(blocking=False):
        _set_model_runtime("busy_fallback", "The local model is already busy, so RAMIFY used the safe catalogue matcher.")
        return None
    try:
        from ramify.agent.langgraph_adapter import LangGraphAdapter

        adapter = LangGraphAdapter()
        runtime = adapter.status()
        if not runtime.get("local_model_available"):
            if runtime.get("ollama_daemon_reachable") and not runtime.get("model_available"):
                _set_model_runtime("model_missing", runtime.get("detail") or "The configured local model is not installed.")
            elif not runtime.get("ollama_daemon_reachable"):
                _set_model_runtime("offline", runtime.get("detail") or "Ollama is offline; deterministic mode is active.")
            else:
                _set_model_runtime("unavailable", runtime.get("detail") or "Local AI is unavailable; deterministic mode is active.")
            return None
        candidates = _candidate_products(candidate_refs)
        if candidate_refs and not candidates:
            return None
        # ChatOllama itself carries the supported HTTP client timeout. Running
        # it synchronously under the single-call lock means a timed-out request
        # cannot survive as an orphaned background worker while another model
        # request starts. That keeps repeated presentation fallbacks bounded.
        model_started = time.perf_counter()
        try:
            reading = adapter.interpret(request_text, candidates)
        except Exception as exc:
            elapsed = time.perf_counter() - model_started
            state = "slow_fallback" if elapsed >= LOCAL_MODEL_CALL_TIMEOUT_SECONDS * 0.9 else "error_fallback"
            detail = (
                f"The local model exceeded the {LOCAL_MODEL_CALL_TIMEOUT_SECONDS:g}-second presentation limit, so RAMIFY used the safe catalogue matcher."
                if state == "slow_fallback"
                else "The local model returned an error, so RAMIFY used the safe catalogue matcher."
            )
            _set_model_runtime(state, detail)
            return None
        elapsed = time.perf_counter() - model_started
        if elapsed > LOCAL_MODEL_CALL_TIMEOUT_SECONDS:
            _set_model_runtime(
                "slow_fallback",
                f"The local model exceeded the {LOCAL_MODEL_CALL_TIMEOUT_SECONDS:g}-second presentation limit, so RAMIFY used the safe catalogue matcher.",
            )
            return None
        _set_model_runtime("ready", "The last local-model request completed inside the presentation limit.")
        return {
            "identifier": reading.identifier,
            "actor_ref": actor_ref,
            "confidence": round(float(reading.confidence), 2),
            "source": adapter.name,
            "note": reading.note or "Matched by the local language model.",
            "candidates": [reading.identifier] if reading.identifier else [],
            "authoritative": False,
            "boundary": "The model interprets the request. The deterministic engine decides trust.",
        }
    except Exception:
        _set_model_runtime("error_fallback", "The optional local AI could not complete, so RAMIFY used the safe catalogue matcher.")
        return None
    finally:
        _MODEL_CALL_SLOT.release()


def interpret(
    request_text: str,
    actor_ref: str = "consumer_v1",
    mode: str = "auto",
    candidate_refs: list[str] | None = None,
) -> dict:
    """Interpret a request and report measured local processing time.

    Exact identifiers bypass the model because asking an LLM to reinterpret an
    already-resolved identifier adds latency and a new failure mode without any
    semantic value. The timing is display-only and never enters the signed
    trust decision.
    """
    started_ns = time.perf_counter_ns()

    def finish(reading: dict) -> dict:
        elapsed_us = max(1, (time.perf_counter_ns() - started_ns) // 1_000)
        reading["latency_us"] = int(elapsed_us)
        reading["latency_ms"] = round(elapsed_us / 1000, 3)
        return reading

    text = request_text.strip()
    if not text:
        raise ValueError("Enter a product name, description, GTIN, SKU or local identifier.")
    if mode not in {"auto", "deterministic", "local_llm"}:
        raise ValueError("mode must be auto, deterministic or local_llm")

    # A single trusted candidate means the shopper already selected an exact
    # catalogue product. Re-asking a language model to identify it adds latency
    # and a failure mode without adding information.
    if candidate_refs and len(candidate_refs) == 1:
        products = _candidate_products(candidate_refs)
        if len(products) == 1:
            chosen = products[0]
            return finish({
                "identifier": chosen["subject_ref"],
                "actor_ref": actor_ref,
                "confidence": 1.0,
                "source": "selected_catalogue_item",
                "note": "Exact product selected from the local catalogue.",
                "candidates": [chosen["subject_ref"]],
                "authoritative": False,
                "boundary": "Interpretation only. The deterministic engine decides trust.",
            })

    # Respect explicit local identifiers before any generative interpretation.
    exact = primitives.identify(text)
    allowed = {p["subject_ref"] for p in _candidate_products(candidate_refs)}
    if exact.get("resolved") and (not candidate_refs or exact["subject_ref"] in allowed):
        return finish(deterministic_interpret(text, actor_ref, candidate_refs))

    if mode in {"auto", "local_llm"}:
        reading = _try_local_model(text, actor_ref, candidate_refs)
        if reading is not None:
            return finish(reading)
        if mode == "local_llm":
            fallback = deterministic_interpret(text, actor_ref, candidate_refs)
            fallback["note"] = "Local model unavailable; " + fallback["note"]
            fallback["source"] = "deterministic_fallback"
            return finish(fallback)

    return finish(deterministic_interpret(text, actor_ref, candidate_refs))


def status() -> dict:
    try:
        from ramify.agent.langgraph_adapter import LangGraphAdapter

        adapter = LangGraphAdapter()
        runtime = adapter.status()
        available = bool(runtime.get("local_model_available"))
        name = adapter.name
    except Exception as exc:
        available = False
        name = "langgraph+ollama:unavailable"
        runtime = {
            "local_model_available": False,
            "dependencies_installed": False,
            "ollama_daemon_reachable": False,
            "model_available": False,
            "model": os.environ.get("RAMIFY_LOCAL_MODEL", "llama3.1"),
            "framework": "LangGraph",
            "provider": "Ollama",
            "detail": "The optional local AI status check could not load.",
            "error_type": type(exc).__name__,
        }
    recent = _model_runtime_snapshot()
    recent_state = recent.get("state", "not_tested")
    fallback_states = {"slow_fallback", "busy_fallback", "error_fallback", "offline", "model_missing", "disabled", "unavailable"}
    active_mode = "deterministic_fallback" if recent_state in fallback_states or not available else "local_llm"
    return {
        **runtime,
        "local_model_available": available,
        "local_model_adapter": name,
        "fallback_available": True,
        "active_mode": active_mode,
        "presentation_state": recent_state,
        "presentation_detail": recent.get("detail"),
        "presentation_timeout_seconds": LOCAL_MODEL_CALL_TIMEOUT_SECONDS,
        "interpretation_path": (
            "LangGraph → Ollama local LLM → known catalogue identifier"
            if active_mode == "local_llm"
            else "deterministic fixed-catalogue fallback"
        ),
        "decision_path": "deterministic RAMIFY checks → policy → sealed receipt",
        "boundary": "AI may interpret and explain. Only the deterministic engine can decide trust.",
    }
