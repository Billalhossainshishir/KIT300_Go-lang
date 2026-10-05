"""Optional PydanticAI adapter for the client-requested framework comparison.

It implements the same narrow protocol as the LangGraph adapter. The package is
not a runtime dependency; the demo remains fully functional without it. When
installed, this adapter can interpret a request and explain a sealed receipt,
but it has no API for creating or changing a trust decision.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from ramify.agent.protocol import Interpretation, bounded_confidence
from ramify.agent import tools


def _loopback_url(value: str) -> bool:
    try:
        parsed = urlparse(value if "://" in value else "http://" + value)
        return (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
    except Exception:
        return False


class PydanticAIAdapter:
    name = f"pydanticai:{os.environ.get('RAMIFY_LOCAL_MODEL', 'llama3.1')}"

    def __init__(self) -> None:
        self._agent = None

    def available(self) -> bool:
        try:
            import pydantic_ai  # noqa: F401
            return os.environ.get("RAMIFY_DISABLE_AGENT") != "1"
        except Exception:
            return False

    def _ensure_agent(self):
        if self._agent is not None:
            return self._agent
        from pydantic_ai import Agent

        model = os.environ.get("RAMIFY_PYDANTICAI_MODEL", "ollama:llama3.1")
        if not model.lower().startswith("ollama:"):
            raise ValueError("RAMIFY PydanticAI comparison is restricted to local Ollama models")
        base_url = os.environ.get("RAMIFY_OLLAMA_BASE_URL", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
        if not _loopback_url(base_url):
            raise ValueError("RAMIFY PydanticAI comparison requires a loopback Ollama endpoint")
        # Build the provider from the URL that was just checked. Passing the
        # "ollama:<name>" string let the library resolve its own endpoint, so the
        # loopback check above enforced nothing (David's L1). Ollama serves an
        # OpenAI-compatible API under /v1.
        from pydantic_ai.providers.openai import OpenAIProvider

        try:
            from pydantic_ai.models.openai import OpenAIChatModel as ChatModel
        except ImportError:  # releases before 1.0 named it OpenAIModel
            from pydantic_ai.models.openai import OpenAIModel as ChatModel

        bound_model = ChatModel(
            model.split(":", 1)[1],
            provider=OpenAIProvider(base_url=base_url.rstrip("/") + "/v1"),
        )
        self._agent = Agent(
            bound_model,
            system_prompt=(
                "Select only a subject_ref from the supplied local catalogue. "
                "Never state a trust verdict or action. Return JSON with identifier, confidence and note."
            ),
        )
        return self._agent

    def interpret(self, request_text: str, known_products: list[dict]) -> Interpretation:
        agent = self._ensure_agent()
        prompt = json.dumps({"request": request_text, "catalogue": known_products})
        result = agent.run_sync(prompt)
        try:
            payload = json.loads(str(result.output))
        except Exception:
            return Interpretation(None, "consumer_v1", 0.0, "unparseable model output")
        # Arrays, null, strings and numbers are valid JSON but not a reading;
        # calling .get on them raised instead of failing cleanly.
        if not isinstance(payload, dict):
            return Interpretation(None, "consumer_v1", 0.0, "model output was not a JSON object")
        # The model may choose only from the candidate set actually supplied to
        # this call. Using the whole catalogue here would let it escape a user's
        # explicit product selection.
        known = {product["subject_ref"] for product in known_products}
        identifier = payload.get("identifier")
        if not isinstance(identifier, str) or identifier not in known:
            return Interpretation(None, "consumer_v1", 0.0, "model named a product outside the supplied candidate set")
        confidence = bounded_confidence(payload.get("confidence", 0.0))
        return Interpretation(
            identifier,
            "consumer_v1",
            confidence,
            str(payload.get("note", ""))[:240],
        )

    def explain(self, receipt: dict) -> str:
        agent = self._ensure_agent()
        safe = {
            "product": receipt.get("product_name"),
            "objective_posture": receipt.get("objective_posture"),
            "actor_decision": receipt.get("actor_decision"),
            "reason_codes": receipt.get("reason_codes", []),
        }
        result = agent.run_sync(
            "Explain this already-final decision in two plain sentences. Do not change it.\n"
            + json.dumps(safe)
        )
        return str(result.output).strip()
