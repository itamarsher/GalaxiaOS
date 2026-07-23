"""Anthropic / Claude implementation of :class:`LLMProvider`.

This is the ONLY module permitted to import the ``anthropic`` SDK. The provider
boundary is enforced by ``make check-providers`` in CI.
"""

from __future__ import annotations

import json
import math

import anthropic

from app.providers import pricing
from app.providers.base import (
    ImageBlock,
    LLMProvider,
    LLMResponse,
    Message,
    Price,
    ProviderError,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
    Usage,
)

# Rough per-image token allowance used only to size the pre-call reservation
# (the real cost reconciles from ``response.usage`` afterwards). A generous
# upper bound so a reservation never under-covers a vision call.
_IMAGE_TOKEN_ESTIMATE_CHARS = 6000

# Above this many output tokens the Anthropic SDK refuses a non-streaming
# request (it estimates the response could exceed the ~10-min HTTP timeout), so
# we transparently switch to streaming and reassemble the final message.
_STREAM_THRESHOLD = 16_000

# Internal tool used to force structured JSON output (see ``complete``).
_JSON_TOOL_NAME = "emit_result"

# Substrings distinguishing a non-retryable billing/quota rejection (account
# out of credit) from an ordinary malformed-request 400 (bad model name,
# invalid tool schema, etc.) — both raise ``anthropic.BadRequestError``.
_BILLING_ERROR_MARKERS = ("credit balance", "insufficient", "quota")


def _is_billing_error(exc: anthropic.BadRequestError) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _BILLING_ERROR_MARKERS)


def _block_text(block: object) -> str:
    """Approximate character length of a structured block (for estimation)."""
    if isinstance(block, TextBlock):
        return block.text
    if isinstance(block, ToolUseBlock):
        return f"{block.name}{block.input}"
    if isinstance(block, ToolResultBlock):
        return block.content
    if isinstance(block, ImageBlock):
        return "x" * _IMAGE_TOKEN_ESTIMATE_CHARS
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
        elif isinstance(b, ImageBlock):
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": b.media_type,
                        "data": b.data,
                    },
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
        return pricing.price_for(self.name, model)

    def max_output_tokens(self, model: str) -> int:
        return pricing.max_output_tokens(self.name, model)

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
        json_schema: dict | None = None,
    ) -> LLMResponse:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": _render_content(m.content)} for m in messages],
        }
        if system:
            kwargs["system"] = system
        if json_schema is not None:
            # Force structured JSON by pinning a single tool: the model must call
            # it, and the SDK returns the arguments already parsed — no
            # hand-written JSON to mis-format.
            kwargs["tools"] = [
                {
                    "name": _JSON_TOOL_NAME,
                    "description": "Return the requested result as structured JSON.",
                    "input_schema": json_schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": _JSON_TOOL_NAME}
        elif tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]

        try:
            if max_tokens > _STREAM_THRESHOLD:
                # Stream to dodge the SDK's non-streaming size guard, then
                # reassemble the same Message object via get_final_message().
                async with client.messages.stream(**kwargs) as stream:
                    resp = await stream.get_final_message()
            else:
                resp = await client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise ProviderError(
                "Anthropic rejected the API key (authentication failed). "
                "Check the key configured for this company.",
                kind="auth",
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError(
                "Anthropic denied access for this API key (check plan/permissions).",
                kind="auth",
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("Anthropic rate limit exceeded; try again shortly.",
                                kind="rate_limit") from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"Anthropic could not find model '{model}'.",
                                kind="bad_request") from exc
        except anthropic.BadRequestError as exc:
            kind = "billing" if _is_billing_error(exc) else "bad_request"
            raise ProviderError(f"Anthropic rejected the request: {exc}", kind=kind) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("Could not reach the Anthropic API (network error).",
                                kind="connection") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic API error (HTTP {exc.status_code}).") from exc
        except anthropic.APIError as exc:
            raise ProviderError(f"Anthropic API call failed: {type(exc).__name__}.") from exc
        finally:
            await client.close()

        if json_schema is not None:
            # Pinned-tool path: the result is the tool call's parsed input.
            payload: dict = {}
            for block in resp.content:
                if block.type == "tool_use":
                    payload = dict(block.input or {})
                    break
            return LLMResponse(
                text=json.dumps(payload),
                usage=Usage(
                    input_tokens=resp.usage.input_tokens,
                    output_tokens=resp.usage.output_tokens,
                ),
                model=resp.model,
                stop_reason=resp.stop_reason or "",
            )

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
