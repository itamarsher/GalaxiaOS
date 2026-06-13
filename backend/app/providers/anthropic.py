"""Anthropic / Claude implementation of :class:`LLMProvider`.

This is the ONLY module permitted to import the ``anthropic`` SDK. The provider
boundary is enforced by ``make check-providers`` in CI.
"""

from __future__ import annotations

import math

import anthropic

from app.providers.base import (
    LLMProvider,
    LLMResponse,
    Message,
    Price,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
    Usage,
)
from app.providers.pricing import price_for


def _block_text(block: object) -> str:
    """Approximate character length of a structured block (for estimation)."""
    if isinstance(block, TextBlock):
        return block.text
    if isinstance(block, ToolUseBlock):
        return f"{block.name}{block.input}"
    if isinstance(block, ToolResultBlock):
        return block.content
    return str(block)


def _message_text(message: Message) -> str:
    """Flatten a message's content to text for cheap token estimation."""
    if isinstance(message.content, str):
        return message.content
    return "".join(_block_text(b) for b in message.content)


def _render_content(content: str | list) -> str | list[dict]:
    """Render a message's content into the Anthropic Messages API shape.

    Plain ``str`` content passes through unchanged (back-compatible). A list of
    structured blocks is mapped to Anthropic content-block dicts.
    """
    if isinstance(content, str):
        return content
    blocks: list[dict] = []
    for b in content:
        if isinstance(b, TextBlock):
            blocks.append({"type": "text", "text": b.text})
        elif isinstance(b, ToolUseBlock):
            blocks.append(
                {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input or {}}
            )
        elif isinstance(b, ToolResultBlock):
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": b.tool_use_id,
                    "content": b.content,
                    "is_error": b.is_error,
                }
            )
        else:  # pragma: no cover - defensive
            raise TypeError(f"Unsupported content block: {type(b).__name__}")
    return blocks


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    default_models = {
        "cheap": "claude-haiku-4-5",
        "planner": "claude-sonnet-4-6",
        "strategic": "claude-opus-4-8",
    }

    def price(self, model: str) -> Price:
        return price_for(self.name, model)

    def estimate_input_tokens(
        self, *, api_key: str, model: str, system: str, messages: list[Message]
    ) -> int:
        """Cheap, dependency-free worst-case estimate for pre-call reservation.

        Reservation only needs an upper-ish bound; the real cost is reconciled
        from ``response.usage`` after the call. ~4 chars/token + a safety margin.
        """
        chars = len(system) + sum(len(_message_text(m)) for m in messages)
        return math.ceil(chars / 3.5) + 256

    async def complete(
        self,
        *,
        api_key: str,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": _render_content(m.content)} for m in messages],
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]

        try:
            resp = await client.messages.create(**kwargs)
        finally:
            await client.close()

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
                )

        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            ),
            model=resp.model,
            stop_reason=resp.stop_reason or "",
        )
