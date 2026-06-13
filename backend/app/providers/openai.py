"""OpenAI implementation of :class:`LLMProvider`.

This is the ONLY module permitted to import the ``openai`` SDK. The provider
boundary is enforced by ``make check-providers`` in CI.
"""

from __future__ import annotations

import json
import math

import openai

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


def _flatten(content) -> str:
    """Render a Message's content (str or list[ContentBlock]) to plain text.

    The native agent loop targets the Anthropic provider, so structured
    tool_use/tool_result blocks rarely reach this provider; flattening keeps it
    safe and provider-agnostic until full OpenAI tool-result mapping is added.
    """
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            parts.append(f"[tool_use {block.name} {block.input}]")
        elif isinstance(block, ToolResultBlock):
            prefix = "tool_error" if block.is_error else "tool_result"
            parts.append(f"[{prefix} {block.content}]")
    return "\n".join(parts)


class OpenAIProvider(LLMProvider):
    name = "openai"
    default_models = {
        "cheap": "gpt-4o-mini",
        "planner": "gpt-4o",
        "strategic": "gpt-4o",
    }

    def price(self, model: str) -> Price:
        return price_for(self.name, model)

    def estimate_input_tokens(
        self, *, api_key: str, model: str, system: str, messages: list[Message]
    ) -> int:
        """Cheap, dependency-free worst-case estimate for pre-call reservation.

        Reservation only needs an upper-ish bound; the real cost is reconciled
        from ``response.usage`` after the call. ~4 chars/token + a safety margin.
        Deliberately avoids any network token-counter.
        """
        chars = len(system) + sum(len(_flatten(m.content)) for m in messages)
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
        client = openai.AsyncOpenAI(api_key=api_key)

        oai_messages: list[dict] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend({"role": m.role, "content": _flatten(m.content)} for m in messages)

        kwargs: dict = {
            "model": model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]

        try:
            resp = await client.chat.completions.create(**kwargs)
        finally:
            await client.close()

        choice = resp.choices[0]
        message = choice.message

        text = message.content or ""

        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            raw = tc.function.arguments or "{}"
            try:
                arguments = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                arguments = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=arguments))

        usage = resp.usage
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
            model=resp.model,
            stop_reason=choice.finish_reason or "",
        )
