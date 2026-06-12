"""Provider-agnostic LLM interface.

This is the *only* abstraction the rest of the system programs against. The
runtime, services, and agents never import a vendor SDK — that lives behind an
:class:`LLMProvider` implementation in this package. Swapping or adding a vendor
(OpenAI, Gemini, OpenAI-compatible) is one new file plus a registry entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    stop_reason: str = ""


@dataclass(frozen=True)
class Price:
    """Per-1M-token prices in cents (e.g. $5.00/MTok -> 500)."""

    input_cents_per_mtok: float
    output_cents_per_mtok: float

    def cost_cents(self, usage: Usage) -> int:
        import math

        c = (
            usage.input_tokens / 1_000_000 * self.input_cents_per_mtok
            + usage.output_tokens / 1_000_000 * self.output_cents_per_mtok
        )
        return max(1, math.ceil(c)) if (usage.input_tokens or usage.output_tokens) else 0


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def price(self, model: str) -> Price: ...

    def estimate_input_tokens(
        self, *, api_key: str, model: str, system: str, messages: list[Message]
    ) -> int: ...

    async def complete(
        self,
        *,
        api_key: str,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse: ...
