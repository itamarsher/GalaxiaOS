"""The Founder MCP tool surface: a user's AI can create/read/steer its own companies,
resolve the gating decisions, and cannot touch companies it doesn't found.

Exercises the ``_call_tool`` dispatch directly against the fixture session (the JSON-RPC
transport is a thin wrapper that only adds token→user_id auth on top).
"""

from __future__ import annotations

import json
import uuid

from app.api import founder_mcp as fm
from app.models import (
    Agent,
    AgentRun,
    Company,
    DecisionRequest,
    Membership,
    Mission,
    Task,
    User,
)
from app.models.enums import (
    AgentRole,
    AgentStatus,
    CompanyStatus,
    DecisionKind,
    DecisionStatus,
    MembershipRole,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from tests.conftest import requires_db

pytestmark = requires_db


async def _active_company_with_founder(db):
    u = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(u)
    await db.flush()
    company = Company(owner_user_id=u.id, name="C", status=CompanyStatus.active)
    db.add(company)
    await db.flush()
    db.add(Membership(user_id=u.id, company_id=company.id, role=MembershipRole.founder))
    return u, company


def _payload(rpc: dict) -> dict:
    return json.loads(rpc["result"]["content"][0]["text"])


async def _user(db) -> uuid.UUID:
    u = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(u)
    await db.flush()
    return u.id


@requires_db
async def test_create_list_snapshot_and_playbook(session_factory):
    async with session_factory() as db:
        uid = await _user(db)
        await db.commit()

    # create_company
    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            1,
            {
                "name": "create_company",
                "arguments": {
                    "mission_text": "Sell handmade widgets online",
                    "budget_cents": 10000,
                },
            },
        )
        cid = _payload(r)["company_id"]
        assert _payload(r)["status"] == "draft"

    # list_companies shows it
    async with session_factory() as db:
        r = await fm._call_tool(db, uid, 2, {"name": "list_companies", "arguments": {}})
        assert any(c["id"] == cid for c in _payload(r)["companies"])

    # get_company_snapshot
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 3, {"name": "get_company_snapshot", "arguments": {"company_id": cid}}
        )
        snap = _payload(r)
        assert snap["company"]["status"] == "draft"
        assert snap["budget"]["limit_cents"] == 10000

    # set_playbook
    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            4,
            {
                "name": "set_playbook",
                "arguments": {"company_id": cid, "playbook": "Be bold and concise."},
            },
        )
        assert _payload(r)["customized"] is True
        got = await db.scalar(fm.select(Company).where(Company.id == uuid.UUID(cid)))
        assert got.playbook == "Be bold and concise."


@requires_db
async def test_edit_mission_resets_and_preserves_involvement(session_factory):
    """edit_mission changes the mission (back to draft) without dropping the gates."""
    async with session_factory() as db:
        uid = await _user(db)
        await db.commit()

    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 1,
            {
                "name": "create_company",
                "arguments": {
                    "mission_text": "Old mission: sell widgets",
                    "budget_cents": 10000,
                    "involvement": "Approve every plan, hire and spend before it proceeds.",
                },
            },
        )
        cid = _payload(r)["company_id"]

    # edit_mission → new mission, company reset to draft
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 2,
            {
                "name": "edit_mission",
                "arguments": {
                    "company_id": cid,
                    "mission_text": "New mission: agent spend guardrails",
                    "constraints": ["stay lean"],
                },
            },
        )
        assert _payload(r)["status"] == "draft"

    async with session_factory() as db:
        mission = await db.scalar(fm.select(Mission).where(Mission.company_id == uuid.UUID(cid)))
        assert mission.raw_text == "New mission: agent spend guardrails"
        assert mission.constraints == ["stay lean"]
        # The founder's involvement (the approval gate) survives the mission change.
        m = await db.scalar(
            fm.select(Membership).where(Membership.company_id == uuid.UUID(cid))
        )
        assert m.involvement == "Approve every plan, hire and spend before it proceeds."


@requires_db
async def test_cannot_touch_a_company_you_dont_found(session_factory):
    async with session_factory() as db:
        owner = await _user(db)
        other = await _user(db)
        await db.commit()
    async with session_factory() as db:
        cid = _payload(
            await fm._call_tool(
                db,
                owner,
                1,
                {
                    "name": "create_company",
                    "arguments": {"mission_text": "A real company", "budget_cents": 5000},
                },
            )
        )["company_id"]

    # A different user's token cannot snapshot or steer it.
    async with session_factory() as db:
        r = await fm._call_tool(
            db, other, 2, {"name": "get_company_snapshot", "arguments": {"company_id": cid}}
        )
        assert "error" in r and "founder" in r["error"]["message"]


@requires_db
async def test_approve_decision_over_mcp(session_factory, monkeypatch):
    enqueued: list = []

    async def _capture(task_id):
        enqueued.append(task_id)

    monkeypatch.setattr(fm, "enqueue_task", _capture)

    async with session_factory() as db:
        u = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(u)
        await db.flush()
        company = Company(owner_user_id=u.id, name="C", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Membership(user_id=u.id, company_id=company.id, role=MembershipRole.founder))
        agent = Agent(company_id=company.id, role=AgentRole.ceo, name="CEO")
        db.add(agent)
        await db.flush()
        run = AgentRun(
            company_id=company.id, trigger=RunTrigger.scheduled, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company.id,
            run_id=run.id,
            root_run_id=run.id,
            agent_id=agent.id,
            goal="do the thing",
            status=TaskStatus.waiting_approval,
        )
        db.add(task)
        await db.flush()
        decision = DecisionRequest(
            company_id=company.id,
            agent_id=agent.id,
            task_id=task.id,
            kind=DecisionKind.plan_approval,
            summary="Approve the plan?",
            status=DecisionStatus.pending,
        )
        db.add(decision)
        await db.commit()
        uid, cid, did, tid = u.id, company.id, decision.id, task.id

    async with session_factory() as db:
        # No note: a note is archived to Company Memory, whose pgvector table is
        # excluded from the test schema — the resolution itself is what we're testing.
        r = await fm._call_tool(
            db,
            uid,
            1,
            {
                "name": "approve_decision",
                "arguments": {"company_id": str(cid), "decision_id": str(did)},
            },
        )
        assert _payload(r)["resolved"] == "approved"

    async with session_factory() as db:
        assert (await db.get(DecisionRequest, did)).status is DecisionStatus.approved
    assert tid in enqueued  # the parked task was resumed + enqueued


@requires_db
async def test_steering_tools(session_factory, monkeypatch):
    enqueued: list = []

    async def _capture(task_id):
        enqueued.append(task_id)

    monkeypatch.setattr(fm, "enqueue_task", _capture)

    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        ceo = Agent(company_id=company.id, role=AgentRole.ceo, name="CEO")
        growth = Agent(company_id=company.id, role=AgentRole.growth, name="Growth")
        db.add_all([ceo, growth])
        await db.commit()
        uid, cid, growth_id = u.id, str(company.id), growth.id

    # list_agents
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 1, {"name": "list_agents", "arguments": {"company_id": cid}}
        )
        roles = {a["role"] for a in _payload(r)["agents"]}
        assert {"ceo", "growth"} <= roles

    # send_founder_message to the CEO → idle agent, so a handler task is spawned + enqueued
    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            2,
            {
                "name": "send_founder_message",
                "arguments": {
                    "company_id": cid,
                    "agent_role": "ceo",
                    "message": "Focus on the launch.",
                },
            },
        )
        out = _payload(r)
        assert out["delivered_to"] == "ceo" and out["spawned"] is True
    assert len(enqueued) == 1  # the spawned handler task was enqueued

    # pause then resume the growth agent
    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            3,
            {"name": "pause_agent", "arguments": {"company_id": cid, "agent_id": str(growth_id)}},
        )
        assert _payload(r)["status"] == "paused"
    async with session_factory() as db:
        assert (await db.get(Agent, growth_id)).status is AgentStatus.paused
        r = await fm._call_tool(
            db,
            uid,
            4,
            {"name": "resume_agent", "arguments": {"company_id": cid, "agent_id": str(growth_id)}},
        )
        assert _payload(r)["status"] == "active"


@requires_db
async def test_send_message_unknown_role_errors(session_factory):
    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        await db.commit()
        uid, cid = u.id, str(company.id)
    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            1,
            {
                "name": "send_founder_message",
                "arguments": {"company_id": cid, "agent_role": "ceo", "message": "hi"},
            },
        )
        assert "error" in r  # no active ceo agent exists → error, not a silent drop
