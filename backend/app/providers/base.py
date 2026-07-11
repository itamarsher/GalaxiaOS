"""Provider-agnostic LLM interface.

This is the *only* abstraction the rest of the system programs against. The
runtime, services, and agents never import a vendor SDK — that lives behind an
:class:`LLMProvider` implementation in this package. Swapping or adding a vendor
(OpenAI, Gemini, OpenAI-compatible) is one new file plus a registry entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Union, runtime_checkable


class ProviderError(Exception):
    """A provider call failed (bad API key, rate limit, upstream/network error).

    Wraps the vendor SDK's exception so callers outside ``app/providers/`` can
    handle provider failures without importing a vendor SDK (see the
    provider-boundary guard). ``kind`` is a coarse, vendor-neutral category
    (``auth`` | ``rate_limit`` | ``connection`` | ``bad_request`` | ``error``).
    """

    def __init__(self, message: str, *, kind: str = "error") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class TextBlock:
    """A plain-text content block within a structured message turn."""

    text: str


@dataclass
class ToolUseBlock:
    """An assistant turn's request to invoke a tool (echoed back to the model).

    ``id`` must match the originating :class:`ToolCall.id` so the model can
    correlate it with the corresponding :class:`ToolResultBlock`.
    """

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResultBlock:
    """A user turn carrying the result of a previously requested tool call.

    ``tool_use_id`` ties the result back to its :class:`ToolUseBlock.id`.
    ``content`` is the tool's observation (text). ``is_error`` flags a failed
    or denied execution.
    """

    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class ImageBlock:
    """An image handed to a vision-capable model as input (e.g. for a critic).

    ``data`` is the raw image bytes encoded as a base64 ASCII string and
    ``media_type`` its MIME type (e.g. ``image/png``). Only user turns carry
    images, and only vision-capable models accept them — every current provider
    model (``claude-*``, ``gpt-4o``) qualifies. This is input-only: the runtime
    never persists image turns in a task transcript.
    """

    data: str
    media_type: str = "image/png"


# A structured turn is an ordered list of content blocks. Plain ``str`` content
# is still accepted (and preferred for simple text-only turns) so existing
# callers need no change.
ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock, ImageBlock]


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str | list[ContentBlock]


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
    #: Default model id per role tier. Keys: "cheap", "planner", "strategic".
    #: Lets the runtime pick a sensible model without hardcoding vendor ids.
    default_models: dict[str, str]

    def price(self, model: str) -> Price: ...

    def max_output_tokens(self, model: str) -> int:
        """Largest ``max_tokens`` value this model accepts for one response."""
        ...

    def context_window_tokens(self, model: str) -> int:
        """Total input context (in tokens) this model accepts."""
        ...

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
        json_schema: dict | None = None,
    ) -> LLMResponse:
        """Run one completion.

        When ``json_schema`` is provided, the provider forces structured JSON
        output (Anthropic via a pinned tool, OpenAI via JSON mode) and the
        returned :attr:`LLMResponse.text` is guaranteed-valid JSON.
        """
        ...
