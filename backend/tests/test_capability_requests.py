"""Founder-initiated capability/bug requests + per-company web search key.

Covers the fix for "I asked an agent to request a capability and it offered to
direct me to the product team": the founder-facing chat now actually files a
platform request instead of role-playing.
"""

from __future__ import annotations

import base64
import os
from types import SimpleNamespace

from sqlalchemy import func, select

from app.integrations.tavily import TavilyWebSearch
from app.integrations.websearch import SimulatedWebSearch
from app.models import Agent, Task
from app.models.enums import AgentRole
from app.runtime.tools.core import WEB_SEARCH_PROVIDER, _resolve_web_search
from app.services import apikeys, copilot, platform_requests
from tests.conftest import requires_db


def _set_master_key() -> None:
    from app.config import settings as app_settings

    app_settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


async def _add_platform_agent(db, company_id):
    agent = Agent(company_id=company_id, role=AgentRole.platform, name="Platform")
    db.add(agent)
    await db.flush()
    return agent


# ── file_request service ──────────────────────────────────────────────────────


@requires_db
async def test_file_request_creates_task_for_platform_agent(session_factory, company_with_budget):
    async with session_factory() as db:
        await _add_platform_agent(db, company_with_budget)
        await db.commit()

    async with session_factory() as db:
        task_id = await platform_requests.file_request(
            db, company_id=company_with_budget, kind="capability",
            title="Real web search", details="agents only get simulated results",
        )
        await db.commit()

    assert task_id is not None
    async with session_factory() as db:
        task = await db.get(Task, task_id)
        agent = await db.get(Agent, task.agent_id)
    assert agent.role is AgentRole.platform
    assert "REQUESTED A CAPABILITY" in task.goal


@requires_db
async def test_file_request_without_platform_agent_returns_none(session_factory, company_with_budget):
    async with session_factory() as db:
        task_id = await platform_requests.file_request(
            db, company_id=company_with_budget, kind="bug", title="x", details="y"
        )
    assert task_id is None


@requires_db
async def test_file_request_unknown_kind_returns_none(session_factory, company_with_budget):
    async with session_factory() as db:
        await _add_platform_agent(db, company_with_budget)
        await db.commit()
    async with session_factory() as db:
        assert await platform_requests.file_request(
            db, company_id=company_with_budget, kind="nonsense", title="x", details="y"
        ) is None


# ── copilot command path ──────────────────────────────────────────────────────


@requires_db
async def test_copilot_command_files_capability_request(
    session_factory, company_with_budget, monkeypatch
):
    enqueued: list = []

    async def _fake_enqueue(task_id, **_):
        enqueued.append(task_id)

    monkeypatch.setattr(copilot, "enqueue_task", _fake_enqueue)
    async with session_factory() as db:
        await _add_platform_agent(db, company_with_budget)
        await db.commit()

    async with session_factory() as db:
        text = await copilot._execute_command(
            db,
            company_id=company_with_budget,
            action={"action": "request_capability", "title": "Real web search",
                    "details": "only simulated results today"},
        )

    assert "Filed a capability request" in text
    assert len(enqueued) == 1
    async with session_factory() as db:
        n = await db.scalar(
            select(func.count()).select_from(Task).where(Task.company_id == company_with_budget)
        )
    assert n == 1


# ── decision-discuss tool handling ────────────────────────────────────────────


@requires_db
async def test_discuss_tool_call_files_request(session_factory, company_with_budget, monkeypatch):
    enqueued: list = []

    async def _fake_enqueue(task_id, **_):
        enqueued.append(task_id)

    monkeypatch.setattr(copilot, "enqueue_task", _fake_enqueue)
    async with session_factory() as db:
        await _add_platform_agent(db, company_with_budget)
        await db.commit()

    resp = SimpleNamespace(
        text="On it.",
        tool_calls=[SimpleNamespace(name="request_capability",
                                    arguments={"title": "Real web search", "details": "..."})],
    )
    async with session_factory() as db:
        confirmations = await copilot._handle_platform_tool_calls(
            db, company_id=company_with_budget, resp=resp
        )

    assert confirmations and "Filed a capability request" in confirmations[0]
    assert len(enqueued) == 1


# ── per-company web search key ────────────────────────────────────────────────


@requires_db
async def test_web_search_defaults_to_simulated_without_key(session_factory, company_with_budget):
    _set_master_key()
    async with session_factory() as db:
        search = await _resolve_web_search(db, company_with_budget)
    assert isinstance(search, SimulatedWebSearch)


@requires_db
async def test_web_search_uses_tavily_when_company_key_set(session_factory, company_with_budget):
    _set_master_key()
    async with session_factory() as db:
        await apikeys.store_key(
            db, company_id=company_with_budget, provider=WEB_SEARCH_PROVIDER, plaintext="tvly-xxx"
        )
        await db.commit()
    async with session_factory() as db:
        search = await _resolve_web_search(db, company_with_budget)
    assert isinstance(search, TavilyWebSearch)
