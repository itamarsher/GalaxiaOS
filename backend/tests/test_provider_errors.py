"""Vendor SDK exceptions are wrapped as the provider-agnostic ProviderError.

This is what lets API endpoints turn an upstream failure (e.g. a bad API key on
/onboarding/{id}/generate) into a clean 502 instead of an unhandled 500 — and
keeps callers outside app/providers/ from importing a vendor SDK.
"""

from __future__ import annotations

import anthropic
import openai
import pytest

from app.providers.anthropic import AnthropicProvider
from app.providers.base import Message, ProviderError
from app.providers.openai import OpenAIProvider


class _FakeMessages:
    def __init__(self, exc: Exception):
        self._exc = exc

    async def create(self, **kwargs):
        raise self._exc


class _FakeClient:
    def __init__(self, exc: Exception):
        self.messages = _FakeMessages(exc)
        self.closed = False

    async def close(self):
        self.closed = True


def _patch_client(monkeypatch, exc: Exception) -> _FakeClient:
    client = _FakeClient(exc)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **_: client)
    return client


def _auth_error() -> anthropic.AuthenticationError:
    # Construct without a live HTTP round-trip.
    return anthropic.AuthenticationError.__new__(anthropic.AuthenticationError)


def _bad_request_error(cls: type[Exception], message: str) -> Exception:
    # Construct without a live HTTP round-trip; set .args directly so str(exc)
    # reproduces the vendor SDK's message text (Exception.__str__ reads args).
    exc = cls.__new__(cls)
    exc.args = (message,)
    return exc


async def test_auth_error_wrapped_with_kind_auth(monkeypatch):
    client = _patch_client(monkeypatch, _auth_error())
    provider = AnthropicProvider()
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            api_key="bad", model="claude-sonnet-4-6", system="", messages=[Message(role="user", content="hi")]
        )
    assert ei.value.kind == "auth"
    assert client.closed  # client is always closed, even on error


async def test_generic_exception_not_swallowed(monkeypatch):
    # A non-vendor error is a real bug and must propagate unchanged (becomes a
    # 500 with CORS via the request-context middleware), not a masked 502.
    _patch_client(monkeypatch, RuntimeError("boom"))
    provider = AnthropicProvider()
    with pytest.raises(RuntimeError):
        await provider.complete(
            api_key="x", model="claude-sonnet-4-6", system="", messages=[Message(role="user", content="hi")]
        )


async def test_anthropic_billing_rejection_wrapped_with_kind_billing(monkeypatch):
    exc = _bad_request_error(
        anthropic.BadRequestError,
        "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
        "'message': 'Your credit balance is too low to access the Anthropic API. "
        "Please go to Plans & Billing to upgrade or purchase credits.'}}",
    )
    _patch_client(monkeypatch, exc)
    provider = AnthropicProvider()
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            api_key="x", model="claude-sonnet-4-6", system="", messages=[Message(role="user", content="hi")]
        )
    assert ei.value.kind == "billing"


async def test_anthropic_ordinary_bad_request_stays_kind_bad_request(monkeypatch):
    # A malformed-request 400 (e.g. an unknown model id) must not be
    # misclassified as billing just because it also raises BadRequestError.
    exc = _bad_request_error(anthropic.BadRequestError, "Error code: 400 - unknown field 'foo'")
    _patch_client(monkeypatch, exc)
    provider = AnthropicProvider()
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            api_key="x", model="claude-sonnet-4-6", system="", messages=[Message(role="user", content="hi")]
        )
    assert ei.value.kind == "bad_request"


class _FakeOAICompletions:
    def __init__(self, exc: Exception):
        self._exc = exc

    async def create(self, **kwargs):
        raise self._exc


class _FakeOAIClient:
    def __init__(self, exc: Exception):
        self.chat = type("_Chat", (), {"completions": _FakeOAICompletions(exc)})()
        self.closed = False

    async def close(self):
        self.closed = True


def _patch_oai_client(monkeypatch, exc: Exception) -> _FakeOAIClient:
    client = _FakeOAIClient(exc)
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_: client)
    return client


async def test_openai_billing_rejection_wrapped_with_kind_billing(monkeypatch):
    exc = _bad_request_error(
        openai.BadRequestError,
        "You exceeded your current quota, please check your plan and billing details.",
    )
    _patch_oai_client(monkeypatch, exc)
    provider = OpenAIProvider()
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            api_key="x", model="gpt-4o", system="", messages=[Message(role="user", content="hi")]
        )
    assert ei.value.kind == "billing"


async def test_openai_ordinary_bad_request_stays_kind_bad_request(monkeypatch):
    exc = _bad_request_error(openai.BadRequestError, "Error code: 400 - unknown field 'foo'")
    _patch_oai_client(monkeypatch, exc)
    provider = OpenAIProvider()
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            api_key="x", model="gpt-4o", system="", messages=[Message(role="user", content="hi")]
        )
    assert ei.value.kind == "bad_request"
