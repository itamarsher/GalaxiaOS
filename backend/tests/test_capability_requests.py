"""Founder-initiated capability/bug requests + per-company web search key.

Covers the fix for "I asked an agent to request a capability and it offered to
direct me to the product team": the founder-facing chat now actually files a
platform request instead of role-playing.
"""

from __future__ import annotations

import base64
import os
import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.integrations.tavily import TavilyWebSearch
from app.models import Agent, Task
from app.models.enums import AgentRole
from app.runtime.tools.core import (
    EMAIL_KEY_PROVIDER,
    WEB_SEARCH_PROVIDER,
    _resolve_email_sender,
    _resolve_web_search,
)
from app.services import apikeys, copilot, platform_requests
from tests.conftest import requires_db


def _set_master_key() -> None:
    from app.config import settings as app_settings

    app_settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


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
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=agent.id,
        goal="g",
        status=TaskStatus.running,
    )
    db.add(task)
    await db.flush()
    return agent, task


# ── file_request service → feature-request backlog ────────────────────────────


@requires_db
async def test_file_request_records_to_backlog(session_factory, company_with_budget):
    from app.models import FeatureRequest, FeatureRequestVote
    from app.models.enums import FeatureRequestKind

    async with session_factory() as db:
        outcome = await platform_requests.file_request(
            db,
            company_id=company_with_budget,
            kind="capability",
            title="Real web search",
            details="agents only get simulated results",
        )
        await db.commit()

    assert outcome is not None
    assert outcome.is_new_feature is True
    assert outcome.votes == 1
    async with session_factory() as db:
        fr = await db.get(FeatureRequest, outcome.feature_id)
        votes = (await db.scalars(select(FeatureRequestVote))).all()
    assert fr.kind is FeatureRequestKind.capability
    assert len(votes) == 1
    assert votes[0].company_id == company_with_budget


@requires_db
async def test_file_request_attributes_user_and_dedupes(session_factory, company_with_budget):
    """Two users in one company asking the same thing → one entry, two votes."""
    from app.models import Company, FeatureRequest, FeatureRequestVote, User

    async with session_factory() as db:
        # The fixture made an owner user; add a second user in the same company.
        company = await db.get(Company, company_with_budget)
        u2 = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(u2)
        await db.flush()
        owner_id, second_id = company.owner_user_id, u2.id
        await db.commit()

    for uid in (owner_id, second_id, owner_id):  # owner asks twice → still one vote
        async with session_factory() as db:
            await platform_requests.file_request(
                db,
                company_id=company_with_budget,
                kind="capability",
                title="Real web search",
                details="need it",
                user_id=uid,
            )
            await db.commit()

    async with session_factory() as db:
        frs = (await db.scalars(select(FeatureRequest))).all()
        votes = (await db.scalars(select(FeatureRequestVote))).all()
    assert len(frs) == 1 and frs[0].vote_count == 2  # two distinct users
    assert {v.user_id for v in votes} == {owner_id, second_id}


@requires_db
async def test_file_request_unknown_kind_returns_none(session_factory, company_with_budget):
    async with session_factory() as db:
        assert (
            await platform_requests.file_request(
                db, company_id=company_with_budget, kind="nonsense", title="x", details="y"
            )
            is None
        )


# ── copilot command path ──────────────────────────────────────────────────────


@requires_db
async def test_copilot_command_records_capability_request(session_factory, company_with_budget):
    from app.models import FeatureRequest

    async with session_factory() as db:
        text = await copilot._execute_command(
            db,
            company_id=company_with_budget,
            action={
                "action": "request_capability",
                "title": "Real web search",
                "details": "only simulated results today",
            },
        )
        await db.commit()

    assert "backlog" in text.lower()
    async with session_factory() as db:
        fr = await db.scalar(select(FeatureRequest))
    assert fr is not None and fr.title == "Real web search" and fr.vote_count == 1


# ── per-company web search key ────────────────────────────────────────────────


@requires_db
async def test_web_search_is_unsupported_without_a_key(session_factory, company_with_budget):
    _set_master_key()
    async with session_factory() as db:
        search, cost, _funding, _reason = await _resolve_web_search(db, company_with_budget)
    # No Tavily key and no global provider -> None, so web_search reports the
    # capability is unsupported (no simulated results are fabricated).
    assert search is None
    assert cost == 0


@requires_db
async def test_web_search_uses_tavily_with_a_cost_when_key_set(
    session_factory, company_with_budget
):
    _set_master_key()
    async with session_factory() as db:
        await apikeys.store_key(
            db, company_id=company_with_budget, provider=WEB_SEARCH_PROVIDER, plaintext="tvly-xxx"
        )
        await db.commit()
    async with session_factory() as db:
        search, cost, _funding, _reason = await _resolve_web_search(db, company_with_budget)
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
        return _FakeSearch(), 5, None, None

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
        return _FakeTavily(), settings.web_search_cost_cents, None, None

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


# ── web_fetch (page extraction, shares the Tavily provider/key) ───────────────


@requires_db
async def test_web_fetch_is_unsupported_without_a_provider(
    session_factory, company_with_budget, monkeypatch
):
    """No provider + founder fallback OFF -> web_fetch reports unsupported.

    (With the fallback ON — the default — it escalates to the founder instead; that
    path is covered in test_web_search_founder_fallback.py.)
    """
    from app.runtime import tools as tools_pkg
    from app.runtime.tools import core

    monkeypatch.setattr(core.settings, "web_search_founder_fallback", False)
    _set_master_key()
    async with session_factory() as db:
        agent, task = await _make_agent_task(db, company_with_budget)
        await db.commit()

    ctx = SimpleNamespace(cost_meter=None)  # unused: it never reaches metering
    async with session_factory() as db:
        outcome = await tools_pkg.execute_tool(
            db,
            ctx,
            agent=agent,
            task=task,
            name="web_fetch",
            args={"url": "https://x.test"},
        )
    assert outcome.is_error is True
    assert "not supported" in outcome.observation.lower()


@requires_db
async def test_web_fetch_requires_a_url(session_factory, company_with_budget):
    from app.runtime import tools as tools_pkg

    async with session_factory() as db:
        agent, task = await _make_agent_task(db, company_with_budget)
        await db.commit()

    ctx = SimpleNamespace(cost_meter=None)
    async with session_factory() as db:
        outcome = await tools_pkg.execute_tool(
            db, ctx, agent=agent, task=task, name="web_fetch", args={}
        )
    assert outcome.is_error is True
    assert "url" in outcome.observation.lower()


@requires_db
async def test_web_fetch_extracts_and_charges_measured_credits(
    session_factory, company_with_budget, monkeypatch
):
    """A paid web_fetch reserves the estimate then commits Tavily's real credits."""
    from app.config import settings
    from app.integrations.websearch import FetchResult
    from app.models import Budget, SpendEntry
    from app.runtime import tools as tools_pkg
    from app.runtime.cost_meter import CostMeter

    class _FakeTavily:
        last_usage_credits = 1
        last_request_id = "req-fetch-1"

        async def extract(self, urls):
            return [FetchResult(url=u, content=f"body of {u}") for u in urls]

    async def _fake_resolve(_db, _cid):
        return _FakeTavily(), settings.web_search_cost_cents, None, None

    monkeypatch.setattr("app.runtime.tools.core._resolve_web_search", _fake_resolve)

    async with session_factory() as db:
        agent, task = await _make_agent_task(db, company_with_budget)
        await db.commit()

    ctx = SimpleNamespace(cost_meter=CostMeter(session_factory))
    async with session_factory() as db:
        outcome = await tools_pkg.execute_tool(
            db,
            ctx,
            agent=agent,
            task=task,
            name="web_fetch",
            args={"urls": ["https://a.test", "https://b.test"]},
        )
    assert outcome.is_error is False
    assert "body of https://a.test" in outcome.observation
    assert "body of https://b.test" in outcome.observation

    async with session_factory() as db:
        budget = await db.scalar(select(Budget).where(Budget.company_id == company_with_budget))
        entry = await db.scalar(
            select(SpendEntry).where(SpendEntry.company_id == company_with_budget)
        )
    # 2 URLs is 1 Tavily credit (basic, ~5 per credit); committed at measured credits.
    assert budget.spent_cents == settings.web_search_cost_cents
    assert budget.reserved_cents == 0
    assert entry is not None and entry.amount_cents == settings.web_search_cost_cents


# ── per-company email (Resend) key ───────────────────────────────────────────


@requires_db
async def test_email_is_unsupported_without_a_key(session_factory, company_with_budget):
    _set_master_key()
    async with session_factory() as db:
        sender = await _resolve_email_sender(db, company_with_budget)
    # No Resend key and no global provider -> None, so send_email reports the
    # capability is unsupported (no mail is faked).
    assert sender is None


@requires_db
async def test_email_uses_resend_when_key_set(session_factory, company_with_budget):
    from app.integrations.resend import ResendEmailSender

    _set_master_key()
    async with session_factory() as db:
        await apikeys.store_key(
            db, company_id=company_with_budget, provider=EMAIL_KEY_PROVIDER, plaintext="re_xxx"
        )
        await db.commit()
    async with session_factory() as db:
        sender = await _resolve_email_sender(db, company_with_budget)
    assert isinstance(sender, ResendEmailSender)
    # The per-company key is what's used — not the (empty) global default.
    assert sender._api_key == "re_xxx"


@requires_db
async def test_email_uses_company_from_address_when_set(session_factory, company_with_budget):
    from app.integrations.resend import ResendEmailSender
    from app.models import Company

    _set_master_key()
    async with session_factory() as db:
        await apikeys.store_key(
            db, company_id=company_with_budget, provider=EMAIL_KEY_PROVIDER, plaintext="re_xxx"
        )
        company = await db.get(Company, company_with_budget)
        company.email_from = "Acme <hello@acme.com>"
        await db.commit()
    async with session_factory() as db:
        sender = await _resolve_email_sender(db, company_with_budget)
    assert isinstance(sender, ResendEmailSender)
    # The founder's verified "From:" overrides the global default.
    assert sender._sender == "Acme <hello@acme.com>"
