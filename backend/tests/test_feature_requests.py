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

    ``is_platform`` designates it as the operator (dogfooding) company — the only one
    the promoter gate authorizes.
    """
    user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(user)
    await db.flush()
    company = Company(owner_user_id=user.id, name="C", status=CompanyStatus.active)
    db.add(company)
    await db.flush()
    if is_platform:
        from app.config import settings

        settings.platform_company_id = str(company.id)
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


# ── agent attribution ─────────────────────────────────────────────────────────


@requires_db
async def test_agent_initiated_request_attributes_the_agent(session_factory):
    """An agent's request records the requesting agent + task, not a user."""
    async with session_factory() as db:
        cid, _uid = await _make_company(db)
        task = await _running_task(db, cid)
        await db.commit()

    async with session_factory() as db:
        task = await db.get(Task, task.id)
        agent = await db.get(Agent, task.agent_id)
        await execute_tool(
            db, object(), agent=agent, task=task,
            name="request_capability",
            args={"title": "Slack tool", "details": "post updates"},
        )
        await db.commit()

    async with session_factory() as db:
        vote = await db.scalar(select(FeatureRequestVote))
    assert vote.user_id is None
    assert vote.agent_id == task.agent_id
    assert vote.task_id == task.id


@requires_db
async def test_two_agents_in_one_company_each_hold_a_vote(session_factory):
    """Distinct agents asking the same thing → one entry, two agent-attributed votes."""
    async with session_factory() as db:
        cid, _uid = await _make_company(db)
        t1 = await _running_task(db, cid)
        # A second, different agent in the same company.
        a2 = Agent(company_id=cid, role=AgentRole.growth, name="Growth")
        db.add(a2)
        await db.flush()
        t2 = Task(
            company_id=cid, run_id=t1.run_id, root_run_id=t1.root_run_id,
            agent_id=a2.id, goal="g2", status=TaskStatus.running,
        )
        db.add(t2)
        await db.commit()
        t1_id, t2_id = t1.id, t2.id

    for tid in (t1_id, t2_id, t1_id):  # first agent asks twice → still one vote
        async with session_factory() as db:
            task = await db.get(Task, tid)
            agent = await db.get(Agent, task.agent_id)
            await execute_tool(
                db, object(), agent=agent, task=task,
                name="request_capability",
                args={"title": "Slack tool", "details": "post updates"},
            )
            await db.commit()

    async with session_factory() as db:
        frs = (await db.scalars(select(FeatureRequest))).all()
        votes = (await db.scalars(select(FeatureRequestVote))).all()
        attribution = await fr_svc.load_attribution(db, frs[0].id)
    assert len(frs) == 1 and frs[0].vote_count == 2  # two distinct agents
    assert len(votes) == 2
    assert sorted(a.agent_name for a in attribution) == ["Growth", "Platform"]


# ── platform marks ready (deliver_feature_request) ────────────────────────────


@requires_db
async def test_deliver_feature_request_gated_to_platform(session_factory):
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
            name="deliver_feature_request", args={"feature_request_id": str(fr_id)},
        )
    assert outcome.is_error is True
    assert "authorized" in outcome.observation.lower()


@requires_db
async def test_deliver_feature_request_marks_delivered_and_notifies(session_factory, monkeypatch):
    notices: list[dict] = []

    async def _capture(_db, **kwargs):
        notices.append(kwargs)
        return None

    monkeypatch.setattr("app.services.memory.write", _capture)

    async with session_factory() as db:
        # A requesting tenant company whose agent asked.
        req_cid, _uid = await _make_company(db)
        req_task = await _running_task(db, req_cid)
        req_task = await db.get(Task, req_task.id)
        req_agent = await db.get(Agent, req_task.agent_id)
        await execute_tool(
            db, object(), agent=req_agent, task=req_task,
            name="request_capability",
            args={"title": "Slack tool", "details": "post updates"},
        )
        # The platform company + agent that will mark it ready.
        plat_cid, _puid = await _make_company(db, is_platform=True)
        plat_task = await _running_task(db, plat_cid)
        await db.commit()
        fr_id = (await db.scalar(select(FeatureRequest))).id

    async with session_factory() as db:
        plat_task = await db.get(Task, plat_task.id)
        plat_agent = await db.get(Agent, plat_task.agent_id)
        outcome = await execute_tool(
            db, object(), agent=plat_agent, task=plat_task,
            name="deliver_feature_request", args={"feature_request_id": str(fr_id)},
        )
        await db.commit()

    assert outcome.is_error is False
    assert "delivered" in outcome.observation.lower()
    async with session_factory() as db:
        fr = await db.get(FeatureRequest, fr_id)
    assert fr.status is FeatureRequestStatus.delivered
    # The requesting company got a notice that names its agent.
    assert len(notices) == 1
    assert notices[0]["company_id"] == req_cid
    assert "Platform" in notices[0]["content"]  # the agent that asked is addressed
    assert notices[0]["structured"]["kind"] == "capability_delivered"


# ── founder-facing view (list_for_company) ────────────────────────────────────


@requires_db
async def test_list_for_company_shows_status_and_requesters(session_factory):
    async with session_factory() as db:
        cid, uid = await _make_company(db)
        other_cid, other_uid = await _make_company(db)
        # This company's founder asks for one thing…
        await fr_svc.record_request(
            db, kind="capability", title="Real web search",
            details="need it", company_id=cid, user_id=uid,
        )
        # …another company asks for something else (must NOT leak into cid's view).
        await fr_svc.record_request(
            db, kind="bug", title="Someone else's bug",
            details="x", company_id=other_cid, user_id=other_uid,
        )
        await db.commit()

    async with session_factory() as db:
        mine = await fr_svc.list_for_company(db, company_id=cid)
    assert len(mine) == 1
    cr = mine[0]
    assert cr.feature_request.title == "Real web search"
    assert cr.feature_request.status is FeatureRequestStatus.open
    assert len(cr.attributions) == 1
    assert cr.attributions[0].user_email is not None


@requires_db
async def test_feature_requests_endpoint_serializes_for_founder(session_factory):
    """The founder API maps the service output to the response DTO, scoped to the company."""
    from types import SimpleNamespace

    from app.api.companies import list_feature_requests

    async with session_factory() as db:
        cid, _uid = await _make_company(db)
        task = await _running_task(db, cid)
        task = await db.get(Task, task.id)
        agent = await db.get(Agent, task.agent_id)
        await execute_tool(
            db, object(), agent=agent, task=task,
            name="request_capability",
            args={"title": "Slack tool", "details": "post updates"},
        )
        await db.commit()

    async with session_factory() as db:
        out = await list_feature_requests(company=SimpleNamespace(id=cid), db=db)
    assert len(out) == 1
    assert out[0].title == "Slack tool"
    assert out[0].kind == "capability"
    assert out[0].status == "open"
    assert out[0].requesters[0].agent_name == "Platform"
