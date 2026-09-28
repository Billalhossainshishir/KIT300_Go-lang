"""Optional PydanticAI adapter used only for architectural comparison.

The adapter is local-only and has no authority to create a RAMIFY trust result.
It explicitly passes the validated loopback endpoint to the provider and fails
closed on malformed model output.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from ramify.agent.protocol import Interpretation


def _loopback_url(value: str) -> bool:
    try:
        parsed = urlparse(value if "://" in value else "http://" + value)
        return (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
    except Exception:
        return False


def _validated_model_and_base() -> tuple[str, str]:
    model = os.environ.get("RAMIFY_PYDANTICAI_MODEL", "ollama:llama3.1")
    if not model.lower().startswith("ollama:"):
        raise ValueError("RAMIFY PydanticAI comparison is restricted to local Ollama models")
    model_name = model.split(":", 1)[1].strip()
    if not model_name:
        raise ValueError("RAMIFY PydanticAI comparison requires a local model name")
    base_url = os.environ.get("RAMIFY_OLLAMA_BASE_URL", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    if not _loopback_url(base_url):
        raise ValueError("RAMIFY PydanticAI comparison requires a loopback Ollama endpoint")
    return model_name, base_url.rstrip("/") + "/v1"


class PydanticAIAdapter:
    name = f"pydanticai:{os.environ.get('RAMIFY_LOCAL_MODEL', 'llama3.1')}"

    def __init__(self) -> None:
        self._agent = None

    def available(self) -> bool:
        if os.environ.get("RAMIFY_DISABLE_AGENT") == "1":
            return False
        try:
            import pydantic_ai  # noqa: F401
            _validated_model_and_base()
            return True
        except Exception:
            return False

    def _ensure_agent(self):
        if self._agent is not None:
            return self._agent
        model_name, base_url = _validated_model_and_base()
        from pydantic_ai import Agent
        try:
            from pydantic_ai.models.openai import OpenAIModel
            from pydantic_ai.providers.openai import OpenAIProvider
            provider = OpenAIProvider(base_url=base_url, api_key="ollama-local-only")
            model = OpenAIModel(model_name, provider=provider)
            self._agent = Agent(model, system_prompt=(
                "Select only a subject_ref from the supplied local catalogue. "
                "Never state a trust verdict or action. Return JSON with identifier, confidence and note."
            ))
        except ImportError:
            # If the installed comparison package is too old for an explicit
            # provider, it is safer to report the adapter unsupported than to
            # silently lose the checked local-only endpoint.
            raise RuntimeError("Installed PydanticAI does not support the required explicit local provider")
        return self._agent

    def interpret(self, request_text: str, known_products: list[dict]) -> Interpretation:
        agent = self._ensure_agent()
        prompt = json.dumps({"request": request_text, "catalogue": known_products})
        result = agent.run_sync(prompt)
        try:
            payload = json.loads(str(result.output))
        except Exception:
            return Interpretation(None, "consumer_v1", 0.0, "unparseable model output")
        if not isinstance(payload, dict):
            return Interpretation(None, "consumer_v1", 0.0, "model output was not a JSON object")
        known = {product["subject_ref"] for product in known_products}
        identifier = payload.get("identifier")
        if identifier not in known:
            return Interpretation(None, "consumer_v1", 0.0, "model named a product outside the supplied candidate set")
        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        return Interpretation(identifier, "consumer_v1", confidence, str(payload.get("note", ""))[:240])

    def explain(self, receipt: dict) -> str:
        agent = self._ensure_agent()
        safe = {
            "product": receipt.get("product_name"),
            "objective_posture": receipt.get("objective_posture"),
            "actor_decision": receipt.get("actor_decision"),
            "reason_codes": receipt.get("reason_codes", []),
        }
        result = agent.run_sync(
            "Explain this already-final decision in two plain sentences. Do not change it.\n" + json.dumps(safe)
        )
        return str(result.output).strip()
