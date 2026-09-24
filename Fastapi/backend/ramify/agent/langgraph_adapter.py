"""Local LangGraph + Ollama adapter for the client demonstration.

The model is deliberately outside RAMIFY's trust-decision boundary:

    free text ──▶ LangGraph/Ollama interpretation ──▶ deterministic RAMIFY engine
                                                        │
                                                        └── sealed receipt
                                                                │
                                      LangGraph/Ollama explanation ◀──┘

The local model may map a shopper's words to a *known* catalogue identifier and
may explain a receipt that has already been sealed. It never supplies a trust
posture, reason code, permitted action, review outcome, or basket authority.

This module is the only place that imports LangGraph or LangChain/Ollama. The
core demo remains usable when Ollama, the model, or these optional frameworks
are unavailable.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ramify.agent import tools
from ramify.agent.protocol import Interpretation

# llama3.1 is the model named in the client setup path. It is configurable so a
# lighter local model can be used on a presentation laptop without touching code.
DEFAULT_MODEL = os.environ.get("RAMIFY_LOCAL_MODEL", "llama3.1")
DEFAULT_BASE_URL = os.environ.get("RAMIFY_OLLAMA_URL", "http://127.0.0.1:11434")
STATUS_TIMEOUT_SECONDS = float(os.environ.get("RAMIFY_OLLAMA_STATUS_TIMEOUT", "1.5"))
MODEL_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("RAMIFY_LOCAL_MODEL_TIMEOUT", "5"))

EXPLAIN_SYSTEM_PROMPT = """\
You explain decisions that have already been made. You never make them.

You will be given a decision receipt produced by a deterministic trust engine.
Write two or three sentences of plain English for someone with no technical
background, covering what was checked, what the outcome was, and why.

Rules you must not break:
- Report only what the receipt says. Do not add findings, reasons or reassurance.
- Never state a posture, verdict or recommendation other than the one in the receipt.
- If the receipt says block or hold, do not soften it.
- The data is synthetic. Do not imply the product or certificate is real.
- Write prose only. No JSON, no bullet points, no headings.
"""

INTERPRET_SYSTEM_PROMPT = """\
You turn a shopper's request into one product identifier from a fixed catalogue.

Reply with JSON only, in this shape:
{"identifier": "<subject_ref or null>", "confidence": <0.0-1.0>, "note": "<short reason>"}

Rules you must not break:
- Use only an identifier that appears in the supplied catalogue.
- If the request does not clearly match a supplied product, return null.
- Never invent an identifier.
- Never decide whether a product is safe, trustworthy, permitted, blocked, or purchasable.
- Keep the note short and describe only what product the request appears to mean.
"""


def _package_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _model_matches(configured: str, installed: str) -> bool:
    """Treat ``llama3.1`` and ``llama3.1:latest`` as the same local model."""
    configured = configured.strip().lower()
    installed = installed.strip().lower()
    if configured == installed:
        return True
    return installed == f"{configured}:latest" or configured == f"{installed}:latest"


def _loopback_url(url: str) -> bool:
    """The client requirement is a local model, so reject remote endpoints."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host:
            return False
        if host == "localhost":
            return True
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _local_json(url: str, timeout: float) -> dict[str, Any]:
    """Read Ollama's loopback API without honouring HTTP proxy settings."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(request, timeout=timeout) as response:  # noqa: S310 - loopback URL is configured locally
        return json.loads(response.read().decode("utf-8"))


def runtime_status(
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = STATUS_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Cheap readiness check; importantly, it does *not* run an inference.

    Ollama exposes its local API on port 11434 and ``/api/tags`` lists pulled
    models. Checking that endpoint avoids loading a multi-gigabyte model just to
    draw a status badge.
    """
    started = time.perf_counter()
    langgraph_installed = _package_present("langgraph")
    ollama_bridge_installed = _package_present("langchain_ollama")
    dependencies_installed = langgraph_installed and ollama_bridge_installed
    daemon_reachable = False
    model_available = False
    detected_models: list[str] = []
    detail = ""

    if os.environ.get("RAMIFY_DISABLE_AGENT") == "1":
        detail = "Local AI is disabled by RAMIFY_DISABLE_AGENT=1."
    elif not _loopback_url(base_url):
        detail = "RAMIFY only permits the presentation LLM through a loopback Ollama endpoint."
    elif not dependencies_installed:
        missing = []
        if not langgraph_installed:
            missing.append("langgraph")
        if not ollama_bridge_installed:
            missing.append("langchain-ollama")
        detail = "Missing Python package(s): " + ", ".join(missing) + "."
    else:
        try:
            payload = _local_json(base_url.rstrip("/") + "/api/tags", timeout)
            daemon_reachable = True
            for item in payload.get("models", []):
                name = str(item.get("name") or item.get("model") or "").strip()
                if name:
                    detected_models.append(name)
            model_available = any(_model_matches(model, name) for name in detected_models)
            if model_available:
                detail = f"{model} is ready in the local Ollama catalogue."
            else:
                detail = f"Ollama is running, but {model} has not been pulled."
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
            detail = "Ollama is not reachable on the configured local endpoint."
            # Keep raw exception detail out of the client-facing UI, but retain
            # the type for developers inspecting the JSON endpoint.
            error_type = type(exc).__name__
        except Exception as exc:  # defensive: status must never break the demo
            detail = "The optional local-model readiness check could not complete."
            error_type = type(exc).__name__
        else:
            error_type = None

    available = (
        os.environ.get("RAMIFY_DISABLE_AGENT") != "1"
        and dependencies_installed
        and daemon_reachable
        and model_available
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "local_model_available": available,
        "dependencies_installed": dependencies_installed,
        "langgraph_installed": langgraph_installed,
        "ollama_bridge_installed": ollama_bridge_installed,
        "ollama_daemon_reachable": daemon_reachable,
        "model_available": model_available,
        "model": model,
        "framework": "LangGraph",
        "provider": "Ollama",
        "base_url": base_url,
        "detected_model_count": len(detected_models),
        "detail": detail,
        "status_check_ms": elapsed_ms,
        "error_type": locals().get("error_type"),
        "decision_authority": "deterministic_ramify_engine_only",
    }


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return "\n".join(chunks).strip()
    return str(content).strip()


def _json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        # Some local models wrap otherwise valid JSON in a short sentence.
        # Recover one object, but never try to infer fields from prose.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(cleaned[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


class LangGraphAdapter:
    """Adapter used by the presentation layer; never imported by the engine."""

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL):
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.name = f"langgraph+ollama:{model}"
        self._model = None
        self._graph = None
        self._interpret_graph = None
        self._explain_graph = None

    def status(self) -> dict[str, Any]:
        return runtime_status(self.model_name, self.base_url)

    def available(self) -> bool:
        return bool(self.status()["local_model_available"])

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        if not _loopback_url(self.base_url):
            raise ValueError("RAMIFY local AI requires a loopback Ollama endpoint")
        from langchain_ollama import ChatOllama  # noqa: PLC0415

        # The model is instantiated lazily and only on a real interpretation or
        # explanation request. Status checks never load the model into memory.
        self._model = ChatOllama(
            model=self.model_name,
            base_url=self.base_url,
            temperature=0,
            num_predict=128,
            keep_alive="30m",
            client_kwargs={"timeout": MODEL_REQUEST_TIMEOUT_SECONDS},
        )
        return self._model

    def _interpret_with_model(self, request_text: str, candidates: list[dict]) -> Interpretation:
        model = self._ensure_model()
        catalogue = json.dumps(
            [{"subject_ref": c["subject_ref"], "name": c["name"]} for c in candidates],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        response = model.invoke(
            [
                ("system", INTERPRET_SYSTEM_PROMPT),
                ("human", f"Catalogue: {catalogue}\n\nShopper request: {request_text}"),
            ]
        )
        parsed = _json_object(_message_text(response.content))
        if parsed is None:
            return Interpretation(None, "consumer_v1", 0.0, "Local model returned an unreadable match.")

        identifier = parsed.get("identifier")
        if identifier in (None, "", "null", "None"):
            identifier = None
        elif not isinstance(identifier, str):
            identifier = None

        known = {product["subject_ref"] for product in candidates}
        if identifier is not None and identifier not in known:
            return Interpretation(
                None,
                "consumer_v1",
                0.0,
                "Local model suggested an identifier outside the supplied catalogue, so RAMIFY discarded it.",
            )

        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        note = str(parsed.get("note") or "Local model matched a known catalogue item.")[:240]
        return Interpretation(identifier, "consumer_v1", confidence, note)

    def _explain_with_model(self, receipt: dict) -> str:
        model = self._ensure_model()
        digest = {
            "product": receipt.get("product_name"),
            "objective_posture": receipt.get("objective_posture"),
            "actor_decision": receipt.get("actor_decision"),
            "actor": receipt.get("actor_label"),
            "narrowed": receipt.get("actor_narrowed"),
            "reason_codes": receipt.get("reason_codes"),
            "findings": [
                {
                    "check": check.get("label"),
                    "outcome": check.get("outcome"),
                    "detail": check.get("detail"),
                }
                for check in receipt.get("check_results", [])
                if check.get("outcome") != "pass"
            ],
            "permitted_action": receipt.get("selected_action"),
        }
        response = model.invoke(
            [
                ("system", EXPLAIN_SYSTEM_PROMPT),
                ("human", json.dumps(digest, ensure_ascii=False, separators=(",", ":"))),
            ]
        )
        return _message_text(response.content)

    def _build_interpret_graph(self):
        """LangGraph is on the actual UI interpretation path, not just a demo stub."""
        if self._interpret_graph is not None:
            return self._interpret_graph
        from typing import TypedDict  # noqa: PLC0415
        from langgraph.graph import END, START, StateGraph  # noqa: PLC0415

        class InterpretTurn(TypedDict, total=False):
            request_text: str
            candidates: list[dict]
            reading: Interpretation

        def model_interpret(state: InterpretTurn) -> InterpretTurn:
            return {
                "reading": self._interpret_with_model(
                    state["request_text"], state.get("candidates") or tools.list_products()
                )
            }

        graph = StateGraph(InterpretTurn)
        graph.add_node("local_llm_interpret", model_interpret)
        graph.add_edge(START, "local_llm_interpret")
        graph.add_edge("local_llm_interpret", END)
        self._interpret_graph = graph.compile()
        return self._interpret_graph

    def _build_explain_graph(self):
        """A separate graph keeps generated prose downstream of the sealed receipt."""
        if self._explain_graph is not None:
            return self._explain_graph
        from typing import TypedDict  # noqa: PLC0415
        from langgraph.graph import END, START, StateGraph  # noqa: PLC0415

        class ExplainTurn(TypedDict, total=False):
            receipt: dict
            explanation: str

        def model_explain(state: ExplainTurn) -> ExplainTurn:
            return {"explanation": self._explain_with_model(state["receipt"])}

        graph = StateGraph(ExplainTurn)
        graph.add_node("local_llm_explain", model_explain)
        graph.add_edge(START, "local_llm_explain")
        graph.add_edge("local_llm_explain", END)
        self._explain_graph = graph.compile()
        return self._explain_graph

    def _build_graph(self):
        """Full agent workflow used by the optional live-model integration test."""
        if self._graph is not None:
            return self._graph
        from typing import TypedDict  # noqa: PLC0415
        from langgraph.graph import END, START, StateGraph  # noqa: PLC0415

        class Turn(TypedDict, total=False):
            request_text: str
            actor_ref: str
            identifier: str | None
            assessment: dict | None
            explanation: str

        def interpret_node(state: Turn) -> Turn:
            candidates = tools.search_products(state["request_text"]) or tools.list_products()
            reading = self._interpret_with_model(state["request_text"], candidates)
            return {"identifier": reading.identifier}

        def assess_node(state: Turn) -> Turn:
            # Critical boundary: no model call exists in this node.
            if not state.get("identifier"):
                return {"assessment": None}
            return {
                "assessment": tools.assess_product(
                    state["identifier"], state.get("actor_ref", "consumer_v1")
                )
            }

        def explain_node(state: Turn) -> Turn:
            assessment = state.get("assessment")
            if not assessment:
                return {"explanation": "No product in the catalogue matched that request."}
            return {"explanation": self._explain_with_model(assessment["receipt"])}

        graph = StateGraph(Turn)
        graph.add_node("interpret", interpret_node)
        graph.add_node("deterministic_assess", assess_node)
        graph.add_node("explain", explain_node)
        graph.add_edge(START, "interpret")
        graph.add_edge("interpret", "deterministic_assess")
        graph.add_edge("deterministic_assess", "explain")
        graph.add_edge("explain", END)
        self._graph = graph.compile()
        return self._graph

    def interpret(self, request_text: str, known_products: list[dict]) -> Interpretation:
        candidates = known_products or tools.list_products()
        result = self._build_interpret_graph().invoke(
            {"request_text": request_text, "candidates": candidates}
        )
        reading = result.get("reading")
        if isinstance(reading, Interpretation):
            return reading
        return Interpretation(None, "consumer_v1", 0.0, "Local AI interpretation was unavailable.")

    def explain(self, receipt: dict) -> str:
        result = self._build_explain_graph().invoke({"receipt": receipt})
        return str(result.get("explanation") or "").strip()

    def run_turn(self, request_text: str, actor_ref: str = "consumer_v1") -> dict:
        """Full graph: free text in, deterministic sealed result + prose out."""
        result = self._build_graph().invoke(
            {"request_text": request_text, "actor_ref": actor_ref}
        )
        return {
            "identifier": result.get("identifier"),
            "assessment": result.get("assessment"),
            "explanation": result.get("explanation", ""),
            "explanation_is_presentation_only": True,
        }
