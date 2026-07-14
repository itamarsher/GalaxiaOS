"""Skill optimizer: usage telemetry, reward signal, and the validation gate.

The pure-logic tests (no DB) drive the reflect→gate loop with a stub cost meter,
so the bounded-edit budget, the gate accept/reject/confidence decision, and the
issue payload are all exercised deterministically. The DB-gated tests cover the
``load_skill`` usage write and the per-skill signal aggregation.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.config import settings
from app.runtime import skill_optimizer as opt
from app.runtime import skills as skills_lib
from app.services.skill_signal import FailureExample, SkillSignal, rank_candidates
from tests.conftest import requires_db

# ── shared fixtures-in-code ───────────────────────────────────────────────────

_CURRENT = """---
name: demo-skill
title: Demo Skill
description: Restated the title here, a weak trigger.
roles: growth
---
# Demo Skill

An intro paragraph long enough to comfortably exceed the two-hundred-character
minimum body length the loader and the optimizer's validator both require, with
enough real substance that it reads like an actual playbook rather than a stub.

## Workflow
1. **Step one.** Do the first thing.
2. **Step two.** Do the second thing.
"""

_REVISED = """---
name: demo-skill
title: Demo Skill
description: Run a demo for a prospect who asked to see the product live.
roles: growth
---
# Demo Skill

An intro paragraph long enough to comfortably exceed the two-hundred-character
minimum body length the loader and the optimizer's validator both require, with
enough real substance that it reads like an actual playbook rather than a stub.

## Workflow
1. **Confirm the goal.** Clarify what the prospect wants to see before starting.
2. **Run the demo.** Walk the core flow end to end.
"""


def _skill():
    return skills_lib.parse_skill_text(_CURRENT, default_name="demo-skill")


def _resolved():
    provider = SimpleNamespace(default_models={"planner": "m"}, name="fake")
    return SimpleNamespace(provider=provider, api_key="k", funding_user_id=None)


class _FakeMeter:
    """A stand-in CostMeter whose run_llm returns queued canned JSON strings."""

    def __init__(self, *texts):
        self._texts = list(texts)
        self.calls: list[dict] = []

    async def run_llm(self, provider, **kw):
        self.calls.append(kw)
        return SimpleNamespace(text=self._texts.pop(0))


def _reflect(changes, *, revised=_REVISED, confidence=0.8):
    return json.dumps(
        {"revised_skill": revised, "changes": changes, "confidence": confidence, "rationale": "why"}
    )


def _gate(winner, margin):
    return json.dumps({"winner": winner, "margin": margin, "rationale": "because"})


def _signal(name="demo-skill"):
    return SkillSignal(
        skill_name=name,
        sample_count=10,
        success_count=4,
        failure_count=6,
        failures=[FailureExample(goal="ship the demo", detail="agent skipped clarifying step")],
    )


async def _optimize(meter):
    ctx = SimpleNamespace(cost_meter=meter)
    return await opt.optimize_skill(
        ctx,
        company_id=uuid.uuid4(),
        resolved=_resolved(),
        skill=_skill(),
        current_text=_CURRENT,
        signal=_signal(),
    )


# ── candidate validation ──────────────────────────────────────────────────────


def test_valid_candidate_accepts_a_well_formed_change():
    assert opt._valid_candidate(_REVISED, skill_name="demo-skill", current_text=_CURRENT)


def test_valid_candidate_rejects_unchanged_empty_short_and_bad_roles():
    # unchanged
    assert not opt._valid_candidate(_CURRENT, skill_name="demo-skill", current_text=_CURRENT)
    # empty
    assert not opt._valid_candidate("", skill_name="demo-skill", current_text=_CURRENT)
    # body too short
    tiny = "---\nname: x\ndescription: a real trigger sentence.\nroles: growth\n---\ntoo short"
    assert not opt._valid_candidate(tiny, skill_name="x", current_text=_CURRENT)
    # unknown role
    bad_role = _REVISED.replace("roles: growth", "roles: wizard")
    assert not opt._valid_candidate(bad_role, skill_name="demo-skill", current_text=_CURRENT)


# ── reflect → gate loop ───────────────────────────────────────────────────────


async def test_accepts_high_confidence_when_gate_margin_clears_auto():
    meter = _FakeMeter(_reflect(["sharpened the trigger", "tightened step 2"]), _gate("B", 4))
    proposal = await _optimize(meter)
    assert proposal is not None
    assert proposal.confidence == "high"
    assert proposal.gate_margin == 4
    assert proposal.new_text == _REVISED.strip()  # optimizer stores the file trimmed
    assert proposal.repo_path == "backend/app/runtime/skills/library/demo-skill.md"
    assert len(meter.calls) == 2  # reflect + gate


async def test_slim_margin_is_low_confidence():
    meter = _FakeMeter(_reflect(["one small fix"]), _gate("B", 1))
    proposal = await _optimize(meter)
    assert proposal is not None and proposal.confidence == "low"


async def test_gate_rejection_yields_no_proposal():
    meter = _FakeMeter(_reflect(["a change"]), _gate("A", 6))
    assert await _optimize(meter) is None


async def test_over_budget_edit_is_rejected_before_the_gate():
    too_many = [f"change {i}" for i in range(settings.skill_optimize_max_edits + 1)]
    meter = _FakeMeter(_reflect(too_many))  # only reflect is queued
    assert await _optimize(meter) is None
    assert len(meter.calls) == 1  # gate never runs — budget clip short-circuits


async def test_empty_change_list_is_a_no_op():
    meter = _FakeMeter(_reflect([]))
    assert await _optimize(meter) is None
    assert len(meter.calls) == 1


async def test_unchanged_revision_is_rejected():
    meter = _FakeMeter(_reflect(["noop"], revised=_CURRENT))
    assert await _optimize(meter) is None


# ── issue payload ─────────────────────────────────────────────────────────────


def test_issue_body_carries_path_content_and_markers():
    proposal = opt.SkillProposal(
        skill_name="demo-skill",
        title="Demo Skill",
        repo_path="backend/app/runtime/skills/library/demo-skill.md",
        new_text=_REVISED,
        changes=["sharpened the trigger"],
        rationale="fixes the skipped clarifying step",
        gate_margin=4,
        confidence="high",
        signal=_signal(),
    )
    body = opt.build_issue_body(proposal)
    assert "backend/app/runtime/skills/library/demo-skill.md" in body
    assert opt._BEGIN in body and opt._END in body
    assert _REVISED in body
    assert "⚠️" not in body  # high confidence → no low-confidence banner


def test_low_confidence_body_has_review_banner():
    proposal = opt.SkillProposal(
        skill_name="demo-skill",
        title="Demo Skill",
        repo_path="backend/app/runtime/skills/library/demo-skill.md",
        new_text=_REVISED,
        changes=["x"],
        rationale="r",
        gate_margin=1,
        confidence="low",
        signal=_signal(),
    )
    assert "⚠️" in opt.build_issue_body(proposal)


# ── ranking ───────────────────────────────────────────────────────────────────


def test_rank_candidates_worst_first_and_filters():
    signals = {
        "healthy": SkillSignal("healthy", sample_count=10, success_count=10, failure_count=0),
        "regressed": SkillSignal("regressed", sample_count=10, success_count=3, failure_count=7),
        "mediocre": SkillSignal("mediocre", sample_count=20, success_count=14, failure_count=6),
        "too-few": SkillSignal("too-few", sample_count=2, success_count=0, failure_count=2),
    }
    ranked = rank_candidates(signals, min_samples=5, success_ceiling=0.8)
    names = [s.skill_name for s in ranked]
    # healthy (100%) is above the ceiling; too-few is under min_samples → both excluded.
    assert names == ["regressed", "mediocre"]


# ── DB-gated: usage write + signal aggregation ────────────────────────────────


async def _make_agent(db, company_id):
    from app.models import Agent
    from app.models.enums import AgentRole

    agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
    db.add(agent)
    await db.flush()
    return agent


async def _make_task(db, company_id, agent_id, *, status):
    from app.models import AgentRun, Task
    from app.models.enums import RunStatus, RunTrigger

    run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    task = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=agent_id,
        goal="demo goal",
        status=status,
        output={"summary": "did the thing"} if status.value == "done" else {"error": "blew up"},
    )
    db.add(task)
    await db.flush()
    return task


@requires_db
async def test_load_skill_records_usage(session_factory, company_with_budget):
    from app.models import SkillUsage
    from app.runtime import tools as tools_pkg

    async with session_factory() as db:
        agent = await _make_agent(db, company_with_budget)
        task = await _make_task(db, company_with_budget, agent.id, status=_status("running"))
        await db.commit()

    ctx = SimpleNamespace()
    async with session_factory() as db:
        agent = await db.get(type(agent), agent.id)
        task = await db.get(type(task), task.id)
        outcome = await tools_pkg.execute_tool(
            db,
            ctx,
            agent=agent,
            task=task,
            name="load_skill",
            args={"name": "writing-great-skills"},
        )
        await db.commit()
    assert outcome.is_error is False

    async with session_factory() as db:
        rows = (await db.scalars(select(SkillUsage))).all()
    assert len(rows) == 1
    assert rows[0].skill_name == "writing-great-skills"
    assert rows[0].task_id == task.id


@requires_db
async def test_collect_aggregates_success_and_failures(session_factory, company_with_budget):
    from app.models import SkillUsage
    from app.services import skill_signal

    async with session_factory() as db:
        agent = await _make_agent(db, company_with_budget)
        done1 = await _make_task(db, company_with_budget, agent.id, status=_status("done"))
        done2 = await _make_task(db, company_with_budget, agent.id, status=_status("done"))
        failed = await _make_task(db, company_with_budget, agent.id, status=_status("failed"))
        for t in (done1, done2, failed):
            db.add(
                SkillUsage(
                    company_id=company_with_budget,
                    task_id=t.id,
                    agent_id=agent.id,
                    skill_name="demo-skill",
                )
            )
        await db.commit()

    async with session_factory() as db:
        signals = await skill_signal.collect(db, company_id=company_with_budget, window_days=30)
    sig = signals["demo-skill"]
    assert sig.sample_count == 3
    assert sig.success_count == 2
    assert sig.failure_count == 1
    assert sig.success_rate == 2 / 3
    assert sig.failures and "blew up" in sig.failures[0].detail


def _status(name):
    from app.models.enums import TaskStatus

    return TaskStatus(name)
