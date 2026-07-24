"""OpenAI implementation of :class:`LLMProvider`.

This is the ONLY module permitted to import the ``openai`` SDK. The provider
boundary is enforced by ``make check-providers`` in CI.
"""

from __future__ import annotations

import json
import math

import openai

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

# Above this many output tokens we stream rather than block on one large
# non-streaming response (which risks an HTTP read timeout).
_STREAM_THRESHOLD = 16_000

# Substrings distinguishing a non-retryable billing/quota rejection (account
# out of credit) from an ordinary malformed-request 400 — both raise
# ``openai.BadRequestError``.
_BILLING_ERROR_MARKERS = ("credit balance", "insufficient", "quota", "billing")


def _is_billing_error(exc: openai.BadRequestError) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _BILLING_ERROR_MARKERS)


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
        elif isinstance(block, ImageBlock):
            # Rough allowance so the pre-call estimate covers a vision input.
            parts.append("x" * 6000)
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
            # plain text (and any image) becomes a trailing role:"user" message.
            text_parts: list[str] = []
            image_parts: list[dict] = []
            for b in m.content:
                if isinstance(b, ToolResultBlock):
                    content = f"ERROR: {b.content}" if b.is_error else b.content
                    out.append(
                        {"role": "tool", "tool_call_id": b.tool_use_id, "content": content}
                    )
                elif isinstance(b, TextBlock):
                    text_parts.append(b.text)
                elif isinstance(b, ImageBlock):
                    image_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{b.media_type};base64,{b.data}"},
                        }
                    )
            if image_parts:
                # A vision turn needs the multimodal content-array shape.
                content_parts: list[dict] = []
                if text_parts:
                    content_parts.append({"type": "text", "text": "\n".join(text_parts)})
                content_parts.extend(image_parts)
                out.append({"role": "user", "content": content_parts})
            elif text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts)})
    return out


class OpenAIProvider(LLMProvider):
    name = "openai"
    default_models = {
        "cheap": "gpt-4o-mini",
        "planner": "gpt-4o",
        "strategic": "gpt-4o",
    }
    #: OpenAI-compatible endpoint. ``None`` means the SDK's default (OpenAI
    #: itself). Subclasses that target an OSS host (OpenRouter, Groq, a
    #: self-hosted vLLM/Ollama server) set this to that host's ``/v1`` base URL.
    base_url: str | None = None
    #: Whether the endpoint honors ``response_format={"type": "json_object"}``.
    #: OpenAI does; some OSS backends ignore it (Ollama uses ``format: "json"``,
    #: vLLM uses ``guided_json``). When false we skip the kwarg and lean on the
    #: prompt's existing "return JSON" instruction rather than sending a param
    #: the endpoint may reject.
    supports_json_mode: bool = True
    #: Whether the endpoint accepts the ``tools`` (function-calling) param. Some
    #: OSS models/hosts reject it; when false we omit it.
    supports_tools: bool = True

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
        json_schema: dict | None = None,
    ) -> LLMResponse:
        client = openai.AsyncOpenAI(api_key=api_key, base_url=self.base_url)

        oai_messages = _to_oai_messages(system, messages)

        kwargs: dict = {
            "model": model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
        }
        if json_schema is not None and self.supports_json_mode:
            # JSON mode: the model is constrained to emit a single valid JSON
            # object. (The prompts already say "JSON", which OpenAI requires.)
            kwargs["response_format"] = {"type": "json_object"}
        if tools and self.supports_tools:
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
            if max_tokens > _STREAM_THRESHOLD:
                # Stream large responses so we don't block on one big call (and
                # risk an HTTP read timeout); reassemble into one LLMResponse.
                text, raw_calls, prompt_tokens, completion_tokens, resp_model, finish = (
                    await self._stream(client, kwargs)
                )
            else:
                resp = await client.chat.completions.create(**kwargs)
                message = resp.choices[0].message
                text = message.content or ""
                raw_calls = [
                    (tc.id, tc.function.name, tc.function.arguments or "{}")
                    for tc in message.tool_calls or []
                ]
                usage = resp.usage
                prompt_tokens = usage.prompt_tokens if usage else 0
                completion_tokens = usage.completion_tokens if usage else 0
                resp_model = resp.model
                finish = resp.choices[0].finish_reason or ""
        except openai.AuthenticationError as exc:
            raise ProviderError(
                "OpenAI rejected the API key (authentication failed). "
                "Check the key configured for this company.",
                kind="auth",
            ) from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderError(
                "OpenAI denied access for this API key (check plan/permissions).",
                kind="auth",
            ) from exc
        except openai.RateLimitError as exc:
            raise ProviderError("OpenAI rate limit exceeded; try again shortly.",
                                kind="rate_limit") from exc
        except openai.NotFoundError as exc:
            raise ProviderError(f"OpenAI could not find model '{model}'.",
                                kind="bad_request") from exc
        except openai.BadRequestError as exc:
            kind = "billing" if _is_billing_error(exc) else "bad_request"
            raise ProviderError(f"OpenAI rejected the request: {exc}", kind=kind) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("Could not reach the OpenAI API (network error).",
                                kind="connection") from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"OpenAI API error (HTTP {exc.status_code}).") from exc
        except openai.APIError as exc:
            raise ProviderError(f"OpenAI API call failed: {type(exc).__name__}.") from exc
        finally:
            await client.close()

        tool_calls: list[ToolCall] = []
        for tc_id, tc_name, tc_args in raw_calls:
            try:
                arguments = json.loads(tc_args or "{}")
            except (json.JSONDecodeError, TypeError) as exc:
                # A tool call's arguments JSON can fail to parse for two very
                # different reasons: the model got cut off mid-argument (finish
                # reason "length" — the arguments are legitimately incomplete,
                # e.g. a long `content` string for save_file), or the model
                # emitted genuinely malformed JSON. Silently defaulting to `{}`
                # used to hide both cases behind "content is empty", which sent
                # the agent chasing the wrong bug. Surface a distinguishable
                # error instead (mirrors the pattern in
                # ``app.services.onboarding._parse_llm_json``).
                if finish == "length":
                    raise ProviderError(
                        f"OpenAI's response was cut off before it finished "
                        f"generating arguments for the '{tc_name}' tool call "
                        "(hit the output token limit). Try again with a "
                        "shorter request.",
                        kind="truncated",
                    ) from exc
                raise ProviderError(
                    f"OpenAI returned malformed arguments for the '{tc_name}' "
                    f"tool call: {exc}",
                    kind="bad_request",
                ) from exc
            tool_calls.append(ToolCall(id=tc_id, name=tc_name, arguments=arguments))

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=Usage(input_tokens=prompt_tokens, output_tokens=completion_tokens),
            model=resp_model,
            stop_reason=finish,
        )

    @staticmethod
    async def _stream(client: openai.AsyncOpenAI, kwargs: dict):
        """Consume a streamed completion into the same fields as one response.

        Returns ``(text, raw_tool_calls, prompt_tokens, completion_tokens,
        model, finish_reason)`` where each raw tool call is
        ``(id, name, arguments_json_str)``.
        """
        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        prompt_tokens = completion_tokens = 0
        resp_model = ""
        finish = ""

        stream = await client.chat.completions.create(
            **kwargs, stream=True, stream_options={"include_usage": True}
        )
        async for chunk in stream:
            if chunk.model:
                resp_model = chunk.model
            if chunk.usage:
                prompt_tokens = chunk.usage.prompt_tokens
                completion_tokens = chunk.usage.completion_tokens
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish = choice.finish_reason
            delta = choice.delta
            if delta is None:
                continue
            if delta.content:
                text_parts.append(delta.content)
            for tcd in delta.tool_calls or []:
                slot = calls.setdefault(tcd.index, {"id": None, "name": None, "args": []})
                if tcd.id:
                    slot["id"] = tcd.id
                if tcd.function and tcd.function.name:
                    slot["name"] = tcd.function.name
                if tcd.function and tcd.function.arguments:
                    slot["args"].append(tcd.function.arguments)

        raw_calls = [
            (c["id"], c["name"], "".join(c["args"])) for _, c in sorted(calls.items())
        ]
        return (
            "".join(text_parts),
            raw_calls,
            prompt_tokens,
            completion_tokens,
            resp_model,
            finish,
        )
