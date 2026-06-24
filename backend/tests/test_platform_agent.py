"""Platform agent: escalation triggers, issue filing, fleet & dispatch wiring.

The Platform agent is dormant — the CEO never dispatches it. It wakes only when
another agent escalates via `report_bug` / `request_capability`, each of which
spawns a queued task to the Platform agent (reusing the same `_spawn_child`
mechanism the CEO uses). Once awake, it files a tracker issue with `open_issue`.
With no external tracker connected (the default), `open_issue` records the request
to company memory instead of fabricating an external issue, so the escalation loop
still completes offline.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.integrations.issues import _DEMAND_MARKER, GitHubIssueTracker
from app.models import Agent, AgentRun, Task
from app.models.enums import (
    AgentRole,
    MemoryType,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.runtime.tools.core import SPECS as CORE_SPECS
from app.services.onboarding import _fleet_specs
from tests.conftest import requires_db


class _FakeCtx:
    """Records enqueued task ids; mirrors the fakes in the other runtime tests."""

    def __init__(self) -> None:
        self.enqueued: list = []

    async def enqueue_task(self, task_id):
        self.enqueued.append(task_id)


async def _make_parent_task(session_factory, company_id, *, with_platform=True):
    async with session_factory() as db:
        # The reporting agent (a functional agent that hit a limitation).
        reporter = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
        db.add(reporter)
        if with_platform:
            db.add(Agent(company_id=company_id, role=AgentRole.platform, name="Platform"))
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id,
            run_id=run.id,
            root_run_id=run.id,
            agent_id=reporter.id,
            goal="grow signups",
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()
        return reporter, task


# ── Triggers spawn a task assigned to the platform agent ──────────────────────


@requires_db
async def test_report_bug_spawns_task_for_platform_agent(session_factory, company_with_budget):
    company_id = company_with_budget
    reporter, task = await _make_parent_task(session_factory, company_id)
    ctx = _FakeCtx()

    async with session_factory() as db:
        outcome = await execute_tool(
            db, ctx, agent=reporter, task=task,
            name="report_bug",
            args={"title": "register_domain crashes", "details": "It 500s on .io"},
        )
        await db.commit()

    # Not terminal / not parked — the reporter carries on with its own task.
    assert outcome.is_error is False
    assert outcome.stop is False
    assert outcome.park is False
    assert len(ctx.enqueued) == 1

    async with session_factory() as db:
        platform = await db.scalar(
            select(Agent).where(
                Agent.company_id == company_id, Agent.role == AgentRole.platform
            )
        )
        child = await db.scalar(
            select(Task).where(Task.parent_task_id == task.id)
        )
    assert child is not None
    assert child.agent_id == platform.id
    assert child.status is TaskStatus.queued
    assert "BUG" in child.goal


@requires_db
async def test_request_capability_spawns_task_for_platform_agent(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    reporter, task = await _make_parent_task(session_factory, company_id)
    ctx = _FakeCtx()

    async with session_factory() as db:
        outcome = await execute_tool(
            db, ctx, agent=reporter, task=task,
            name="request_capability",
            args={"title": "need a Slack tool", "details": "to post launch updates"},
        )
        await db.commit()

    assert outcome.is_error is False
    assert outcome.park is False
    assert len(ctx.enqueued) == 1

    async with session_factory() as db:
        platform = await db.scalar(
            select(Agent).where(
                Agent.company_id == company_id, Agent.role == AgentRole.platform
            )
        )
        child = await db.scalar(select(Task).where(Task.parent_task_id == task.id))
    assert child is not None
    assert child.agent_id == platform.id
    assert "CAPABILITY" in child.goal


@requires_db
async def test_report_bug_without_platform_agent_is_graceful(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    reporter, task = await _make_parent_task(session_factory, company_id, with_platform=False)
    ctx = _FakeCtx()

    async with session_factory() as db:
        outcome = await execute_tool(
            db, ctx, agent=reporter, task=task,
            name="report_bug",
            args={"title": "x", "details": "y"},
        )
        await db.commit()

    assert outcome.is_error is True
    assert "No Platform agent" in outcome.observation
    assert ctx.enqueued == []
    async with session_factory() as db:
        child = await db.scalar(select(Task).where(Task.parent_task_id == task.id))
    assert child is None


# ── open_issue records internally when no external tracker is connected ────────


@requires_db
async def test_open_issue_records_internally_and_writes_memory(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    # A platform agent on a task is filing the issue.
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.platform, name="Platform")
        db.add(agent)
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id,
            run_id=run.id,
            root_run_id=run.id,
            agent_id=agent.id,
            goal="file an issue",
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()

    # The memory table is excluded from the test schema (pgvector), so record the
    # write / dedupe lookup instead of hitting it — we only need the audit-trail call.
    recorded: list[dict] = []

    async def _fake_write(db, **kwargs):
        recorded.append(kwargs)
        return None

    async def _no_existing(db, **kwargs):
        return None

    monkeypatch.setattr("app.services.memory.write", _fake_write)
    monkeypatch.setattr("app.services.memory.find_latest_by_title", _no_existing)

    async with session_factory() as db:
        outcome = await execute_tool(
            db, object(), agent=agent, task=task,
            name="open_issue",
            args={"title": "Fix .io registration", "body": "stack trace…", "labels": ["bug"]},
        )
        await db.commit()

    # No external tracker connected -> recorded internally, not fabricated, demand 1.
    assert outcome.is_error is False
    assert "recorded internally" in outcome.observation
    assert "company memory" in outcome.observation
    assert "demand: 1" in outcome.observation
    # Audit trail written to memory with the demand counter seeded.
    assert len(recorded) == 1
    assert recorded[0]["type"] is MemoryType.result
    assert "Fix .io registration" in recorded[0]["title"]
    assert recorded[0]["structured"]["request_count"] == 1


@requires_db
async def test_open_issue_internal_dedupes_and_counts_repeat_requests(
    session_factory, company_with_budget, monkeypatch
):
    """A repeat request bumps the counter on the existing memory, not a new write."""
    from types import SimpleNamespace

    company_id = company_with_budget
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.platform, name="Platform")
        db.add(agent)
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=agent.id, goal="file an issue", status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()

    wrote: list[dict] = []
    existing = SimpleNamespace(structured={"request_count": 2}, content="old")

    async def _fake_write(db, **kwargs):  # pragma: no cover - must not run
        wrote.append(kwargs)
        return None

    async def _found(db, **kwargs):
        return existing

    monkeypatch.setattr("app.services.memory.write", _fake_write)
    monkeypatch.setattr("app.services.memory.find_latest_by_title", _found)

    async with session_factory() as db:
        outcome = await execute_tool(
            db, object(), agent=agent, task=task,
            name="open_issue",
            args={"title": "need a Slack tool", "body": "to post updates", "labels": ["enhancement"]},
        )
        await db.commit()

    assert outcome.is_error is False
    assert "demand now 3" in outcome.observation  # 2 -> 3
    assert existing.structured["request_count"] == 3
    assert wrote == []  # no duplicate memory written


# ── GitHub report_issue: dedupe + "+1" comments (network-free mock transport) ──


def _github_tracker(handler) -> GitHubIssueTracker:
    return GitHubIssueTracker(
        token="ghp_x", repo="o/r", transport=httpx.MockTransport(handler)
    )


# Built from the real marker so the count logic and the fixtures stay in sync.
_DEMAND_COMMENT_PLACEHOLDER = f"{_DEMAND_MARKER}\n+1 — agent needs this"


def _demand_comments(n: int) -> list[dict]:
    """``n`` marked demand comments plus an unrelated human comment (must be ignored)."""
    return [{"body": _DEMAND_COMMENT_PLACEHOLDER} for _ in range(n)] + [
        {"body": "just a human chiming in, no marker here"}
    ]


@pytest.mark.asyncio
async def test_report_issue_opens_new_when_no_duplicate():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(f"{request.method} {path}")
        if path == "/search/issues":
            return httpx.Response(200, json={"items": []})  # nothing matches
        if request.method == "POST" and path == "/repos/o/r/issues":
            return httpx.Response(
                201, json={"id": 111, "number": 7, "html_url": "https://gh/o/r/issues/7"}
            )
        if request.method == "POST" and path == "/repos/o/r/issues/7/comments":
            return httpx.Response(201, json={"id": 1})
        if request.method == "GET" and path == "/repos/o/r/issues/7/comments":
            return httpx.Response(200, json=_demand_comments(1))
        return httpx.Response(404)  # pragma: no cover

    result = await _github_tracker(handler).report_issue(
        title="Add a Slack tool", body="to post updates", labels=["enhancement"]
    )
    assert result.created is True
    assert result.number == 7
    assert result.demand == 1  # seeded so demand starts at 1 (human comment ignored)
    assert "POST /repos/o/r/issues" in calls  # a new issue was actually created
    assert "POST /repos/o/r/issues/7/comments" in calls  # +1 comment posted


@pytest.mark.asyncio
async def test_report_issue_comments_on_existing_duplicate_instead_of_filing():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(f"{request.method} {path}")
        if path == "/search/issues":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 9, "number": 5, "title": "Add a Slack tool",
                         "html_url": "https://gh/o/r/issues/5"}
                    ]
                },
            )
        if request.method == "POST" and path == "/repos/o/r/issues/5/comments":
            return httpx.Response(201, json={"id": 1})
        if request.method == "GET" and path == "/repos/o/r/issues/5/comments":
            return httpx.Response(200, json=_demand_comments(4))
        return httpx.Response(404)  # pragma: no cover

    result = await _github_tracker(handler).report_issue(
        title="Add a Slack tool", body="to post updates", labels=["enhancement"]
    )
    assert result.created is False  # commented on the existing one
    assert result.number == 5
    assert result.demand == 4  # current demand (4 marked comments; human one ignored)
    # Crucially, no new issue was POSTed — only the +1 comment.
    assert "POST /repos/o/r/issues" not in calls
    assert "POST /repos/o/r/issues/5/comments" in calls


@pytest.mark.asyncio
async def test_report_issue_title_match_is_exact_not_fuzzy():
    """A fuzzy search hit with a different title must NOT be treated as a duplicate."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/search/issues":
            return httpx.Response(
                200,
                json={"items": [{"id": 1, "number": 2, "title": "Add a Slack BOT",
                                 "html_url": "https://gh/o/r/issues/2"}]},
            )
        if request.method == "POST" and path == "/repos/o/r/issues":
            return httpx.Response(
                201, json={"id": 3, "number": 8, "html_url": "https://gh/o/r/issues/8"}
            )
        if request.method == "POST" and path == "/repos/o/r/issues/8/comments":
            return httpx.Response(201, json={"id": 1})
        if request.method == "GET" and path == "/repos/o/r/issues/8/comments":
            return httpx.Response(200, json=_demand_comments(1))
        return httpx.Response(404)  # pragma: no cover

    result = await _github_tracker(handler).report_issue(
        title="Add a Slack tool", body="x", labels=None
    )
    assert result.created is True
    assert result.number == 8


@pytest.mark.asyncio
async def test_report_issue_explains_rejected_token_not_missing():
    """A set-but-invalid token (401) must NOT be reported as 'token missing'.

    Regression: a founder who entered a GitHub token in onboarding saw the agent
    claim the key "wasn't set" — really GitHub rejected an expired/invalid token.
    """
    from app.integrations.issues import IssueTrackerError

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/issues":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(IssueTrackerError) as exc:
        await _github_tracker(handler).report_issue(title="x", body="y", labels=None)
    msg = str(exc.value)
    assert "401" in msg and "is set" in msg
    assert "missing" not in msg.lower()


@pytest.mark.asyncio
async def test_report_issue_explains_forbidden_scope():
    """403 names the scope/permission problem rather than a generic failure."""
    from app.integrations.issues import IssueTrackerError

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/issues":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(403, json={"message": "Forbidden"})

    with pytest.raises(IssueTrackerError) as exc:
        await _github_tracker(handler).report_issue(title="x", body="y", labels=None)
    msg = str(exc.value)
    assert "403" in msg and "o/r" in msg


@pytest.mark.asyncio
async def test_open_issue_explains_repo_not_found():
    """404 says the token can't see the repo, not that it's unset."""
    from app.integrations.issues import IssueTrackerError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    with pytest.raises(IssueTrackerError) as exc:
        await _github_tracker(handler).open_issue(title="x", body="y", labels=None)
    msg = str(exc.value)
    assert "404" in msg and "o/r" in msg
    assert "missing" not in msg.lower()


# ── Fleet membership & dispatch isolation ─────────────────────────────────────


def test_platform_agent_in_default_fleet():
    roles = {s["role"] for s in _fleet_specs([])}
    assert "platform" in roles


def test_platform_agent_backfilled_when_omitted():
    roles = {s["role"] for s in _fleet_specs([{"role": "ceo"}, {"role": "growth"}])}
    assert "platform" in roles


def test_platform_not_in_dispatch_task_enum():
    """The CEO's dispatch_task must NOT be able to wake the platform agent."""
    dispatch = next(s for s in CORE_SPECS if s.name == "dispatch_task")
    role_enum = dispatch.input_schema["properties"]["role"]["enum"]
    assert "platform" not in role_enum


def test_platform_tools_available_to_all_agents():
    names = {s.name for s in TOOL_SPECS}
    for expected in ("report_bug", "request_capability", "open_issue"):
        assert expected in names
