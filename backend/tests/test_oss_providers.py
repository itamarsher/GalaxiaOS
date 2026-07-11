"""Open-source providers over OpenAI-compatible endpoints (no network).

Covers: the ``base_url`` seam is actually passed to the client, existing OpenAI
usage is unchanged, capability flags gate the JSON/tools kwargs, per-provider
price/max tables resolve, the registry lists the aggregators (and gates
``openai_compat`` on its setting), and BYOK ``resolve_provider`` picks an OSS
provider by the stored key's provider name.
"""

from __future__ import annotations

import base64
import os
import uuid

import openai
import pytest

from app.providers.base import Message
from app.providers.oss import (
    GroqProvider,
    OpenRouterProvider,
    TogetherProvider,
)
from app.providers.registry import get_provider, supported_providers
from tests.conftest import requires_db

AGGREGATORS = [OpenRouterProvider, GroqProvider, TogetherProvider]


# ── static shape ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cls", AGGREGATORS)
def test_provider_shape(cls):
    p = cls()
    assert p.name
    assert p.base_url and p.base_url.startswith("https://")
    for tier in ("cheap", "planner", "strategic"):
        assert p.default_models[tier]
    # Aggregators speak the OpenAI wire protocol, incl. JSON mode + tools.
    assert p.supports_json_mode is True
    assert p.supports_tools is True


@pytest.mark.parametrize("cls", AGGREGATORS)
def test_price_and_max_output_known_and_unknown(cls):
    p = cls()
    planner = p.default_models["planner"]
    known = p.price(planner)
    assert known.input_cents_per_mtok > 0 and known.output_cents_per_mtok > 0
    assert p.max_output_tokens(planner) > 0
    assert p.context_window_tokens(planner) > 0
    # Unknown model ids fall back to the conservative OSS defaults, not a crash.
    assert p.price("no-such-model") is p.default_price
    assert p.max_output_tokens("no-such-model") == p.default_max_output
    assert p.context_window_tokens("no-such-model") == p.default_context_window


# ── the base_url seam actually reaches the client ───────────────────────────


class _Capture:
    """Records the kwargs AsyncOpenAI was constructed and called with."""

    def __init__(self):
        self.client_kwargs: dict = {}
        self.create_kwargs: dict = {}


def _fake_openai(capture: _Capture):
    resp = _resp()

    class _Completions:
        async def create(self, **kwargs):
            capture.create_kwargs = kwargs
            return resp

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class _FakeClient:
        def __init__(self, **kwargs):
            capture.client_kwargs = kwargs
            self.chat = _Chat()

        async def close(self):
            pass

    return _FakeClient


def _resp():
    class _Msg:
        content = "hi"
        tool_calls = None

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Usage:
        prompt_tokens = 3
        completion_tokens = 1

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()
        model = "test-model"

    return _Resp()


async def _run(provider, monkeypatch, **overrides):
    capture = _Capture()
    monkeypatch.setattr(openai, "AsyncOpenAI", _fake_openai(capture))
    kwargs = dict(
        api_key="k",
        model=provider.default_models["cheap"],
        system="sys",
        messages=[Message(role="user", content="hi")],
    )
    kwargs.update(overrides)
    await provider.complete(**kwargs)
    return capture


@pytest.mark.parametrize("cls", AGGREGATORS)
async def test_base_url_passed_to_client(cls, monkeypatch):
    provider = cls()
    capture = await _run(provider, monkeypatch)
    assert capture.client_kwargs["base_url"] == provider.base_url
    assert capture.client_kwargs["api_key"] == "k"


async def test_openai_provider_passes_none_base_url(monkeypatch):
    """Back-compat: plain OpenAI must still hit its default endpoint."""
    from app.providers.openai import OpenAIProvider

    capture = await _run(OpenAIProvider(), monkeypatch)
    assert capture.client_kwargs["base_url"] is None


# ── capability flags gate the optional kwargs ───────────────────────────────


async def test_json_mode_disabled_omits_response_format(monkeypatch):
    """A provider with supports_json_mode=False must not send response_format."""

    class _NoJson(OpenRouterProvider):
        supports_json_mode = False

    capture = await _run(_NoJson(), monkeypatch, json_schema={"type": "object"})
    assert "response_format" not in capture.create_kwargs


async def test_json_mode_enabled_sends_response_format(monkeypatch):
    capture = await _run(OpenRouterProvider(), monkeypatch, json_schema={"type": "object"})
    assert capture.create_kwargs["response_format"] == {"type": "json_object"}


# ── registry + BYOK wiring ──────────────────────────────────────────────────


def test_registry_lists_aggregators():
    for name in ("openrouter", "groq", "together"):
        assert name in supported_providers()
        assert get_provider(name).name == name


def test_openai_compat_gated_off_without_base_url():
    # No ABOS_OPENAI_COMPAT_BASE_URL in the test env => not registered, so a
    # founder can't store a key that resolves to a dead endpoint.
    assert "openai_compat" not in supported_providers()


@requires_db
async def test_resolve_provider_picks_oss_by_stored_key(session_factory):
    """BYOK: a stored 'openrouter' key resolves to the OpenRouter provider."""
    from app.config import settings as app_settings

    app_settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()

    from app.models import Company, User
    from app.models.enums import CompanyStatus
    from app.services import apikeys

    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()

        await apikeys.store_key(
            db, company_id=company.id, provider="openrouter", plaintext="sk-or-test"
        )
        await db.commit()

        resolved = await apikeys.resolve_provider(db, company_id=company.id)
        assert resolved is not None
        provider, key = resolved
        assert provider.name == "openrouter"
        assert key == "sk-or-test"
