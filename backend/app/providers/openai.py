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

    Used only for the pre-call token estimate; the actual request is built by
    :func:`_to_oai_messages`, which maps structured blocks to OpenAI's native
    tool-calling shape.
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


def _to_oai_messages(system: str, messages: list[Message]) -> list[dict]:
    """Map provider-agnostic messages to OpenAI Chat Completions messages.

    - plain-string turns pass through as ``{role, content}``;
    - an assistant turn's :class:`ToolUseBlock`s become ``tool_calls`` on a
      single assistant message (``content`` may be ``None``);
    - each :class:`ToolResultBlock` becomes its own ``{role: "tool",
      tool_call_id, content}`` message (OpenAI requires one per tool call),
      correlated by ``tool_use_id`` == the original tool call id.
    """
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})

    for m in messages:
        if isinstance(m.content, str):
            out.append({"role": m.role, "content": m.content})
            continue

        if m.role == "assistant":
            text = "\n".join(b.text for b in m.content if isinstance(b, TextBlock))
            tool_calls = [
                {
                    "id": b.id,
                    "type": "function",
                    "function": {"name": b.name, "arguments": json.dumps(b.input)},
                }
                for b in m.content
                if isinstance(b, ToolUseBlock)
            ]
            msg: dict = {"role": "assistant", "content": text or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
        else:
            # User turn: tool_result blocks become role:"tool" messages; any
            # plain text becomes a trailing role:"user" message.
            text_parts: list[str] = []
            for b in m.content:
                if isinstance(b, ToolResultBlock):
                    content = f"ERROR: {b.content}" if b.is_error else b.content
                    out.append(
                        {"role": "tool", "tool_call_id": b.tool_use_id, "content": content}
                    )
                elif isinstance(b, TextBlock):
                    text_parts.append(b.text)
            if text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts)})
    return out


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

        oai_messages = _to_oai_messages(system, messages)

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
