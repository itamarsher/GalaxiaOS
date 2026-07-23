"""A tool call's arguments JSON can fail to parse for two different reasons:
the model was cut off mid-argument (finish_reason "length") or it emitted
genuinely malformed JSON. Regression coverage for issue #242: silently
defaulting to `{}` on either made ``save_file`` report "content is empty"
even when the model *did* try to send content — just truncated content.
"""

from __future__ import annotations

import openai
import pytest

from app.providers.base import Message, ProviderError
from app.providers.openai import OpenAIProvider


class _FakeFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id: str, name: str, arguments: str):
        self.id = id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, tool_calls):
        self.content = None
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, tool_calls, finish_reason: str):
        self.message = _FakeMessage(tool_calls)
        self.finish_reason = finish_reason


class _FakeUsage:
    prompt_tokens = 100
    completion_tokens = 8192


class _FakeResp:
    def __init__(self, tool_calls, finish_reason: str):
        self.choices = [_FakeChoice(tool_calls, finish_reason)]
        self.usage = _FakeUsage()
        self.model = "gpt-4o"


def _patch_client(monkeypatch, resp):
    class _Completions:
        async def create(self, **kwargs):
            return resp

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class _FakeClient:
        def __init__(self, **kwargs):
            self.chat = _Chat()

        async def close(self):
            pass

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)


async def test_truncated_tool_call_arguments_raise_distinguishable_error(monkeypatch):
    # Arguments cut off mid-string (as if `max_tokens` hit while streaming out
    # a long `content` field for save_file), paired with OpenAI's finish_reason
    # for hitting the output token ceiling.
    truncated_args = '{"name": "report.md", "category": "reports", "content": "some long tex'
    resp = _FakeResp(
        tool_calls=[_FakeToolCall("call_1", "save_file", truncated_args)],
        finish_reason="length",
    )
    _patch_client(monkeypatch, resp)

    provider = OpenAIProvider()
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            api_key="k",
            model="gpt-4o",
            system="",
            messages=[Message(role="user", content="write a report")],
        )
    assert ei.value.kind == "truncated"
    assert "cut off" in str(ei.value)
    assert "save_file" in str(ei.value)


async def test_malformed_non_truncated_tool_call_arguments_raise_bad_request(monkeypatch):
    # Invalid JSON that was NOT cut off by the token limit — a different bug
    # in the model's output, not a truncation.
    resp = _FakeResp(
        tool_calls=[_FakeToolCall("call_1", "save_file", "{not valid json}")],
        finish_reason="stop",
    )
    _patch_client(monkeypatch, resp)

    provider = OpenAIProvider()
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            api_key="k",
            model="gpt-4o",
            system="",
            messages=[Message(role="user", content="write a report")],
        )
    assert ei.value.kind == "bad_request"
    assert "malformed" in str(ei.value)


async def test_valid_tool_call_arguments_still_parse(monkeypatch):
    """Non-regression: well-formed arguments are unaffected by the new checks."""
    resp = _FakeResp(
        tool_calls=[_FakeToolCall("call_1", "save_file", '{"name": "a.md", "content": "hi"}')],
        finish_reason="stop",
    )
    _patch_client(monkeypatch, resp)

    provider = OpenAIProvider()
    result = await provider.complete(
        api_key="k",
        model="gpt-4o",
        system="",
        messages=[Message(role="user", content="write a report")],
    )
    (call,) = result.tool_calls
    assert call.arguments == {"name": "a.md", "content": "hi"}
