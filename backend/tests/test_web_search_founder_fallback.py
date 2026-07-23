"""Human-backed web search: when no automated provider is connected, web_search /
web_fetch route to the FOUNDER (a DM they answer) instead of reporting unsupported.
Pure routing test — the provider resolution and the founder escalation are stubbed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.runtime.tools import chat as tools_chat
from app.runtime.tools import core
from app.runtime.tools.base import ToolOutcome


def _task():
    return SimpleNamespace(company_id=uuid.uuid4(), id=uuid.uuid4())


@pytest.fixture
def _no_provider(monkeypatch):
    async def _none(db, company_id):
        return None, 0, None, None  # (provider, cost_cents, funding_user_id, reason)

    monkeypatch.setattr(core, "_resolve_web_search", _none)


async def test_web_search_asks_founder_when_no_provider(monkeypatch, _no_provider):
    captured = {}

    async def _fake_escalate(db, ctx, *, agent, task, summary):
        captured["summary"] = summary
        return ToolOutcome(observation="asked the founder", park=True)

    monkeypatch.setattr(tools_chat, "escalate_to_founder", _fake_escalate)
    monkeypatch.setattr(core.settings, "web_search_founder_fallback", True)

    out = await core._web_search(
        None, None, agent=SimpleNamespace(id=uuid.uuid4()), task=_task(),
        args={"query": "who are the top indie hackers"},
    )
    assert out.park is True
    assert "WEB SEARCH" in captured["summary"] and "top indie hackers" in captured["summary"]


async def test_web_search_unsupported_when_fallback_off(monkeypatch, _no_provider):
    monkeypatch.setattr(core.settings, "web_search_founder_fallback", False)
    out = await core._web_search(
        None, None, agent=SimpleNamespace(id=uuid.uuid4()), task=_task(),
        args={"query": "x"},
    )
    assert out.is_error and "not supported" in out.observation
