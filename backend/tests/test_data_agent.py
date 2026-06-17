"""Data agent: codebase-reading tools, default-fleet membership, egress policies.

Covers the two halves of the Data agent's job: reading THIS repo (capability a)
and controlling external data sharing via governance policies (capability b),
plus its guaranteed presence in the default fleet.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, AgentRun, Policy, Task
from app.models.enums import (
    AgentRole,
    PolicyEffect,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.tools import execute_tool
from app.runtime.tools.code import _REPO_ROOT
from app.services import governance as gov
from app.services.onboarding import _fleet_specs
from tests.conftest import requires_db

# ── Capability (a): codebase readability (no DB needed) ───────────────────────


async def test_read_repo_file_reads_known_file():
    outcome = await execute_tool(
        None, object(), agent=None, task=None,
        name="read_repo_file", args={"path": "backend/app/config.py"},
    )
    assert outcome.is_error is False
    assert "backend/app/config.py" in outcome.observation


async def test_read_repo_file_rejects_traversal():
    outcome = await execute_tool(
        None, object(), agent=None, task=None,
        name="read_repo_file", args={"path": "../../etc/passwd"},
    )
    assert outcome.is_error is True
    assert "outside the repository" in outcome.observation


async def test_read_repo_file_missing_is_error():
    outcome = await execute_tool(
        None, object(), agent=None, task=None,
        name="read_repo_file", args={"path": "backend/does/not/exist.py"},
    )
    assert outcome.is_error is True


async def test_list_repo_files_relative_and_excludes_junk():
    outcome = await execute_tool(
        None, object(), agent=None, task=None,
        name="list_repo_files", args={"subdir": "backend/app"},
    )
    assert outcome.is_error is False
    paths = outcome.observation.splitlines()[1:]  # drop the header line
    assert any(p == "backend/app/config.py" for p in paths)
    # Repo-relative (not absolute) and no junk dirs / binaries leaked through.
    assert not any(p.startswith(str(_REPO_ROOT)) for p in paths)
    for p in paths:
        assert "__pycache__" not in p
        assert "/.git/" not in p
        assert "node_modules" not in p
        assert not p.endswith(".pyc")


# ── Default fleet membership ──────────────────────────────────────────────────


def test_data_agent_in_default_fleet():
    roles = {s["role"] for s in _fleet_specs([])}
    assert "data" in roles


def test_data_agent_backfilled_when_omitted():
    # An LLM-provided fleet that omits data still gets one appended.
    roles = {s["role"] for s in _fleet_specs([{"role": "ceo"}, {"role": "growth"}])}
    assert "data" in roles


# ── Capability (b): external-sharing policy is enforced by governance ──────────


async def _make_data_task(session_factory, company_id):
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.data, name="Data Lead")
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
            goal="g",
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()
        return agent, task


@requires_db
async def test_set_external_sharing_policy_is_enforced_by_governance(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    agent, task = await _make_data_task(session_factory, company_id)

    # Default: no policy → governance allows the egress tool.
    async with session_factory() as db:
        effect = await gov.evaluate(
            db, company_id=company_id, action={"tool": "send_email", "agent_role": "growth"}
        )
    assert effect is PolicyEffect.allow

    # Data agent denies email egress.
    async with session_factory() as db:
        outcome = await execute_tool(
            db, object(), agent=agent, task=task,
            name="set_external_sharing_policy",
            args={"tool": "send_email", "effect": "deny", "reason": "PII risk"},
        )
        await db.commit()
    assert outcome.is_error is False

    async with session_factory() as db:
        effect = await gov.evaluate(
            db, company_id=company_id, action={"tool": "send_email", "agent_role": "growth"}
        )
    assert effect is PolicyEffect.deny

    # Re-setting upserts (no duplicate rows) and changes the effect.
    async with session_factory() as db:
        await execute_tool(
            db, object(), agent=agent, task=task,
            name="set_external_sharing_policy",
            args={"tool": "send_email", "effect": "require_approval"},
        )
        await db.commit()
    async with session_factory() as db:
        count = len(
            (
                await db.scalars(
                    select(Policy).where(
                        Policy.company_id == company_id,
                        Policy.name == "Data egress: send_email",
                    )
                )
            ).all()
        )
        effect = await gov.evaluate(
            db, company_id=company_id, action={"tool": "send_email", "agent_role": "growth"}
        )
    assert count == 1
    assert effect is PolicyEffect.require_approval


@requires_db
async def test_set_external_sharing_policy_rejects_unknown_tool(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    agent, task = await _make_data_task(session_factory, company_id)
    async with session_factory() as db:
        outcome = await execute_tool(
            db, object(), agent=agent, task=task,
            name="set_external_sharing_policy",
            args={"tool": "read_metrics", "effect": "deny"},
        )
        await db.commit()
    assert outcome.is_error is True


@requires_db
async def test_list_data_policies(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _make_data_task(session_factory, company_id)
    async with session_factory() as db:
        empty = await execute_tool(
            db, object(), agent=agent, task=task,
            name="list_data_policies", args={},
        )
    assert "No external-sharing policies" in empty.observation

    async with session_factory() as db:
        await execute_tool(
            db, object(), agent=agent, task=task,
            name="set_external_sharing_policy",
            args={"tool": "run_ad_campaign", "effect": "require_approval"},
        )
        await db.commit()
    async with session_factory() as db:
        listed = await execute_tool(
            db, object(), agent=agent, task=task,
            name="list_data_policies", args={},
        )
    assert "run_ad_campaign: require_approval" in listed.observation
