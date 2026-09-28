"""The adapter boundary — component 6.

Imports no agent framework, and neither does anything that imports it, so a
LangGraph adapter can be swapped for PydanticAI, Google ADK or Microsoft Agent
Framework without touching components 1 to 5 or the interface. The
demonstration must not live inside whichever framework wins.

An adapter may interpret a request and explain a finished receipt. It may not
produce a posture, verdict, reason code or action — the engine does that, and
the receipt is sealed before an adapter ever sees it.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Interpretation:
    """What the model understood the user to be asking for."""

    identifier: str | None
    actor_ref: str
    confidence: float
    note: str = ""


@runtime_checkable
class AgentAdapter(Protocol):
    name: str

    def available(self) -> bool:
        """Whether this adapter can run right now. The demo must work with no
        model present, so every caller checks rather than assuming."""

    def interpret(self, request_text: str, known_products: list[dict]) -> Interpretation:
        """Map free text onto one product identifier. Never a verdict."""

    def explain(self, receipt: dict) -> str:
        """Describe a sealed receipt in plain English.

        The argument is a read-only copy and the caller keeps nothing but the
        returned string.
        """
