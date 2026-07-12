"""Feature-request backlog service + the gated abos promoter.

Covers the redesign where `request_capability` / `report_bug` accrue demand in a
shared, deduplicated backlog (tracking which companies/users asked), and only the
abos company's Platform agent can promote an entry into a real tracker issue.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.integrations.issues import IssueResult
from app.models import (
    Agent,
    AgentRun,
    Company,
    FeatureRequest,
    FeatureRequestVote,
    Membership,
    Task,
    User,
)
from app.models.enums import (
    AgentRole,
    CompanyStatus,
    FeatureRequestKind,
    FeatureRequestStatus,
    MembershipRole,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.tools import execute_tool
from app.runtime.tools import platform as platform_tools
from app.services import feature_requests as fr_svc
from tests.conftest import requires_db


async def _make_company(
    db, *, with_member: bool = False, is_platform: bool = False
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a company (+ owner user, optionally a membership). Returns (company, user).

    ``is_platform`` marks it as the platform (dogfooding) company — the only one the
    promoter gate authorizes.
    """
    user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(user)
    await db.flush()
    company = Company(
        owner_user_id=user.id, name="C", status=CompanyStatus.active, is_platform=is_platform
    )
    db.add(company)
    await db.flush()
    if with_member:
        db.add(
            Membership(user_id=user.id, company_id=company.id, role=MembershipRole.founder)
        )
        await db.flush()
    return company.id, user.id


async def _running_task(db, company_id) -> Task:
    agent = Agent(company_id=company_id, role=AgentRole.platform, name="Platform")
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
    return task


# ── service: dedup + voting ───────────────────────────────────────────────────


@requires_db
async def test_same_feature_from_two_companies_collapses_with_two_votes(session_factory):
    async with session_factory() as db:
        c1, u1 = await _make_company(db)
        c2, u2 = await _make_company(db)
        await db.commit()

    for cid, uid in ((c1, u1), (c2, u2)):
        async with session_factory() as db:
            await fr_svc.record_request(
                db, kind="capability", title="Real web search",
                details="agents need it", company_id=cid, user_id=uid,
            )
            await db.commit()

    async with session_factory() as db:
        frs = (await db.scalars(select(FeatureRequest))).all()
        votes = (await db.scalars(select(FeatureRequestVote))).all()
    assert len(frs) == 1  # deduped by title across companies
    assert frs[0].vote_count == 2
    assert {v.company_id for v in votes} == {c1, c2}


@requires_db
async def test_kind_and_title_form_the_dedup_key(session_factory):
    """Same title, different kind → two distinct entries."""
    async with session_factory() as db:
        cid, uid = await _make_company(db)
        await db.commit()
    async with session_factory() as db:
        await fr_svc.record_request(
            db, kind="bug", title="Exports break", details="x", company_id=cid, user_id=uid
        )
        await fr_svc.record_request(
            db, kind="capability", title="Exports break", details="y", company_id=cid, user_id=uid
        )
        await db.commit()
    async with session_factory() as db:
        frs = (await db.scalars(select(FeatureRequest))).all()
    assert {fr.kind for fr in frs} == {FeatureRequestKind.bug, FeatureRequestKind.capability}


@requires_db
async def test_list_open_orders_by_demand(session_factory):
    async with session_factory() as db:
        c1, u1 = await _make_company(db)
        c2, u2 = await _make_company(db)
        await db.commit()
    async with session_factory() as db:
        # "Popular" gets two votes; "Niche" gets one.
        await fr_svc.record_request(db, kind="capability", title="Popular", details="d", company_id=c1, user_id=u1)
        await fr_svc.record_request(db, kind="capability", title="Popular", details="d", company_id=c2, user_id=u2)
        await fr_svc.record_request(db, kind="capability", title="Niche", details="d", company_id=c1, user_id=u1)
        await db.commit()
    async with session_factory() as db:
        entries = await fr_svc.list_open(db)
    assert [e.title for e in entries] == ["Popular", "Niche"]


# ── promoter gating ───────────────────────────────────────────────────────────


@requires_db
async def test_promote_denied_for_non_abos_company(session_factory):
    # A plain tenant company (is_platform=False) → the promoter gate denies it.
    async with session_factory() as db:
        cid, uid = await _make_company(db, with_member=True, is_platform=False)
        out = await fr_svc.record_request(
            db, kind="capability", title="X", details="d", company_id=cid, user_id=uid
        )
        task = await _running_task(db, cid)
        await db.commit()
        fr_id = out.feature_id

    async with session_factory() as db:
        task = await db.get(Task, task.id)
        agent = await db.get(Agent, task.agent_id)
        outcome = await execute_tool(
            db, object(), agent=agent, task=task,
            name="promote_feature_request", args={"feature_request_id": str(fr_id)},
        )
    assert outcome.is_error is True
    assert "authorized" in outcome.observation.lower()


@requires_db
async def test_promote_files_issue_and_marks_promoted(session_factory, monkeypatch):
    filed: list = []

    class _FakeTracker:
        async def report_issue(self, *, title, body, labels=None):
            filed.append((title, body, labels))
            return IssueResult(
                id="9", number=42, url="https://gh/o/r/issues/42",
                provider="github", created=True, demand=3,
            )

    async def _fake_resolve(_db, _cid):
        return _FakeTracker()

    async def _fake_write(_db, **kwargs):  # memory table is excluded from the test schema
        return None

    monkeypatch.setattr(platform_tools, "_resolve_issue_tracker", _fake_resolve)
    monkeypatch.setattr("app.services.memory.write", _fake_write)

    async with session_factory() as db:
        # The platform company is the one authorized to promote.
        cid, uid = await _make_company(db, with_member=True, is_platform=True)
        out = await fr_svc.record_request(
            db, kind="capability", title="Real web search",
            details="agents only get stubs", company_id=cid, user_id=uid,
        )
        task = await _running_task(db, cid)
        await db.commit()
        fr_id = out.feature_id

    async with session_factory() as db:
        task = await db.get(Task, task.id)
        agent = await db.get(Agent, task.agent_id)
        outcome = await execute_tool(
            db, object(), agent=agent, task=task,
            name="promote_feature_request", args={"feature_request_id": str(fr_id)},
        )
        await db.commit()

    assert outcome.is_error is False
    assert "#42" in outcome.observation
    assert len(filed) == 1
    title, body, labels = filed[0]
    assert title == "Real web search"
    assert labels == ["enhancement"]
    assert "Demand:" in body  # body summarizes who asked

    async with session_factory() as db:
        fr = await db.get(FeatureRequest, fr_id)
    assert fr.status is FeatureRequestStatus.promoted
    assert fr.github_issue_number == 42
    assert fr.github_issue_url == "https://gh/o/r/issues/42"


@requires_db
async def test_list_feature_requests_tool_gated(session_factory):
    async with session_factory() as db:
        # Not the platform company → the backlog-listing tool is refused.
        cid, _uid = await _make_company(db, with_member=True, is_platform=False)
        task = await _running_task(db, cid)
        await db.commit()
    async with session_factory() as db:
        task = await db.get(Task, task.id)
        agent = await db.get(Agent, task.agent_id)
        outcome = await execute_tool(
            db, object(), agent=agent, task=task,
            name="list_feature_requests", args={},
        )
    assert outcome.is_error is True
    assert "abos" in outcome.observation.lower()
