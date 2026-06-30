"""Vendor SDK exceptions are wrapped as the provider-agnostic ProviderError.

This is what lets API endpoints turn an upstream failure (e.g. a bad API key on
/onboarding/{id}/generate) into a clean 502 instead of an unhandled 500 — and
keeps callers outside app/providers/ from importing a vendor SDK.
"""

from __future__ import annotations

import anthropic
import pytest

from app.providers.anthropic import AnthropicProvider
from app.providers.base import Message, ProviderError


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


async def test_auth_error_wrapped_with_kind_auth(monkeypatch):
    client = _patch_client(monkeypatch, _auth_error())
    provider = AnthropicProvider()
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            api_key="bad", model="claude-sonnet-4-6", system="", messages=[Message(role="user", content="hi")]
        )
    assert ei.value.kind == "auth"
    assert client.closed  # client is always closed, even on error


def _bad_request(message: str) -> anthropic.BadRequestError:
    exc = anthropic.BadRequestError.__new__(anthropic.BadRequestError)
    exc.message = message
    return exc


async def test_insufficient_credit_wrapped_with_kind(monkeypatch):
    # A drained account comes back as a 400 whose body says the credit balance is
    # too low; it must be mapped to the dedicated ``insufficient_credits`` kind
    # (not generic ``bad_request``) so the runtime pauses the fleet for a top-up.
    _patch_client(
        monkeypatch,
        _bad_request("Your credit balance is too low to access the Anthropic API."),
    )
    provider = AnthropicProvider()
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            api_key="k", model="claude-sonnet-4-6", system="",
            messages=[Message(role="user", content="hi")],
        )
    assert ei.value.kind == "insufficient_credits"


async def test_ordinary_bad_request_stays_bad_request(monkeypatch):
    # A genuinely malformed request keeps the ``bad_request`` kind — only a
    # balance message escalates to ``insufficient_credits``.
    _patch_client(monkeypatch, _bad_request("messages.0: invalid role 'wizard'"))
    provider = AnthropicProvider()
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            api_key="k", model="claude-sonnet-4-6", system="",
            messages=[Message(role="user", content="hi")],
        )
    assert ei.value.kind == "bad_request"


async def test_generic_exception_not_swallowed(monkeypatch):
    # A non-vendor error is a real bug and must propagate unchanged (becomes a
    # 500 with CORS via the request-context middleware), not a masked 502.
    _patch_client(monkeypatch, RuntimeError("boom"))
    provider = AnthropicProvider()
    with pytest.raises(RuntimeError):
        await provider.complete(
            api_key="x", model="claude-sonnet-4-6", system="", messages=[Message(role="user", content="hi")]
        )
