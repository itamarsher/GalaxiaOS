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


async def _make_agent_task(db, company_id):
    """Persist an agent + run + running task (so spend entries' FKs resolve)."""
    from app.models import AgentRun
    from app.models.enums import RunStatus, RunTrigger, TaskStatus

    agent = Agent(company_id=company_id, role=AgentRole.research, name="Research")
    db.add(agent)
    await db.flush()
    run = AgentRun(company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    task = Task(
        company_id=company_id, run_id=run.id, root_run_id=run.id,
        agent_id=agent.id, goal="g", status=TaskStatus.running,
    )
    db.add(task)
    await db.flush()
    return agent, task


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
async def test_web_search_is_unsupported_without_a_key(session_factory, company_with_budget):
    _set_master_key()
    async with session_factory() as db:
        search, cost = await _resolve_web_search(db, company_with_budget)
    # No Tavily key and no global provider -> None, so web_search reports the
    # capability is unsupported (no simulated results are fabricated).
    assert search is None
    assert cost == 0


@requires_db
async def test_web_search_uses_tavily_with_a_cost_when_key_set(session_factory, company_with_budget):
    _set_master_key()
    async with session_factory() as db:
        await apikeys.store_key(
            db, company_id=company_with_budget, provider=WEB_SEARCH_PROVIDER, plaintext="tvly-xxx"
        )
        await db.commit()
    async with session_factory() as db:
        search, cost = await _resolve_web_search(db, company_with_budget)
    assert isinstance(search, TavilyWebSearch)
    assert cost > 0  # a real provider has a metered cost


@requires_db
async def test_real_web_search_reserves_and_charges_the_budget(
    session_factory, company_with_budget, monkeypatch
):
    """A paid web search goes through the CostMeter: budget is debited the cost."""
    from app.integrations.websearch import SearchResult
    from app.models import Budget, SpendEntry
    from app.runtime import tools as tools_pkg
    from app.runtime.cost_meter import CostMeter

    class _FakeSearch:
        async def search(self, query, *, max_results=5):
            return [SearchResult(title="t", url="https://x", snippet="s")]

    # Force a real (cost-bearing) provider without touching the network.
    async def _fake_resolve(_db, _cid):
        return _FakeSearch(), 5

    monkeypatch.setattr("app.runtime.tools.core._resolve_web_search", _fake_resolve)

    async with session_factory() as db:
        agent, task = await _make_agent_task(db, company_with_budget)
        await db.commit()

    ctx = SimpleNamespace(cost_meter=CostMeter(session_factory))
    async with session_factory() as db:
        outcome = await tools_pkg.execute_tool(
            db, ctx, agent=agent, task=task, name="web_search", args={"query": "pricing"}
        )
    assert outcome.is_error is False

    async with session_factory() as db:
        budget = await db.scalar(select(Budget).where(Budget.company_id == company_with_budget))
        entry = await db.scalar(
            select(SpendEntry).where(SpendEntry.company_id == company_with_budget)
        )
    assert budget.spent_cents == 5  # real final cost subtracted
    assert budget.reserved_cents == 0  # reservation released after commit
    assert entry is not None and entry.amount_cents == 5


@requires_db
async def test_web_search_commits_measured_credits_not_the_estimate(
    session_factory, company_with_budget, monkeypatch
):
    """The meter reconciles to Tavily's reported credits, not the reserved guess.

    The provider reserves a basic-depth estimate (1 credit) but the call reports
    2 credits consumed, so the committed actual is ``2 × web_search_cost_cents``.
    """
    from app.config import settings
    from app.integrations.websearch import SearchResult
    from app.models import Budget, ExternalCharge, SpendEntry
    from app.runtime import tools as tools_pkg
    from app.runtime.cost_meter import CostMeter

    class _FakeTavily:
        # Populated by ``search`` the way TavilyWebSearch sets it from the body.
        last_usage_credits = 2
        last_request_id = "req-abc123"

        async def search(self, query, *, max_results=5):
            return [SearchResult(title="t", url="https://x", snippet="s")]

    # Reserve the basic-depth estimate (1 credit) even though the call bills 2.
    async def _fake_resolve(_db, _cid):
        return _FakeTavily(), settings.web_search_cost_cents

    monkeypatch.setattr("app.runtime.tools.core._resolve_web_search", _fake_resolve)

    async with session_factory() as db:
        agent, task = await _make_agent_task(db, company_with_budget)
        await db.commit()

    ctx = SimpleNamespace(cost_meter=CostMeter(session_factory))
    async with session_factory() as db:
        outcome = await tools_pkg.execute_tool(
            db, ctx, agent=agent, task=task, name="web_search", args={"query": "pricing"}
        )
    assert outcome.is_error is False

    expected = 2 * settings.web_search_cost_cents
    async with session_factory() as db:
        budget = await db.scalar(select(Budget).where(Budget.company_id == company_with_budget))
        entry = await db.scalar(
            select(SpendEntry).where(SpendEntry.company_id == company_with_budget)
        )
        charge = await db.scalar(
            select(ExternalCharge).where(ExternalCharge.company_id == company_with_budget)
        )
    assert budget.spent_cents == expected  # measured (2 credits), not the 1-credit estimate
    assert budget.reserved_cents == 0
    assert entry is not None and entry.amount_cents == expected
    # The Tavily request id is kept for the auditable vendor trail.
    assert charge is not None and charge.external_ref == "req-abc123"
    assert charge.payload and charge.payload.get("credits") == 2
