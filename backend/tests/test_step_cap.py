"""Step-cap timeout: honest summary + a distinct terminal status (issue #222).

A task that exhausts ``max_steps_per_task`` without the agent voluntarily
stopping used to finish as ``done`` with a bare ``"step cap reached"``
placeholder — misrepresenting unfinished work as a real result. It now
recaps what actually happened and lands in ``needs_continuation`` instead.
"""

from __future__ import annotations

import uuid

from app.models import Agent, AgentRun, Task
from app.models.enums import AgentRole, RunStatus, RunTrigger, TaskStatus
from app.providers.base import LLMResponse, Message, TextBlock, Usage
from app.runtime.backends.native import NativeBackend
from app.runtime.tools.core import _collect_results
from app.services import reputation
from app.services import tasks as task_svc
from app.services.budget import BudgetExceeded
from tests.conftest import requires_db


class _FakeCostMeter:
    """Records the run_llm call and returns a canned recap."""

    def __init__(self, text: str = "Recapped partial progress.", *, raise_budget=False):
        self._text = text
        self._raise_budget = raise_budget
        self.calls: list[dict] = []

    async def run_llm(self, provider, **kwargs):
        self.calls.append(kwargs)
        if self._raise_budget:
            raise BudgetExceeded("company", 100, 0)
        return LLMResponse(text=self._text, usage=Usage(1, 1), model="p")


class _FakeTask:
    def __init__(self, goal="Make a page"):
        self.id = uuid.uuid4()
        self.company_id = uuid.uuid4()
        self.agent_id = uuid.uuid4()
        self.goal = goal


class _FakeProvider:
    default_models: dict = {}


def _messages():
    return [
        Message(role="user", content="Begin: launch the company"),
        Message(role="assistant", content=[TextBlock(text="Working on it.")]),
    ]


# ── _summarize_step_cap: pure recap logic, no DB ──────────────────────────────
async def test_summarize_step_cap_returns_llm_recap():
    meter = _FakeCostMeter("Did X and Y; still needs Z.")
    task = _FakeTask()

    class _Ctx:
        cost_meter = meter

    summary = await NativeBackend()._summarize_step_cap(
        _Ctx(), task, provider=_FakeProvider(), api_key="k", model="m", messages=_messages()
    )
    assert summary == "Did X and Y; still needs Z."
    assert len(meter.calls) == 1


async def test_summarize_step_cap_handles_empty_transcript():
    class _Ctx:
        cost_meter = _FakeCostMeter()

    summary = await NativeBackend()._summarize_step_cap(
        _Ctx(), _FakeTask(), provider=_FakeProvider(), api_key="k", model="m", messages=[]
    )
    assert "any progress" in summary.lower()


async def test_summarize_step_cap_falls_back_when_budget_exhausted():
    class _Ctx:
        cost_meter = _FakeCostMeter(raise_budget=True)

    summary = await NativeBackend()._summarize_step_cap(
        _Ctx(), _FakeTask(), provider=_FakeProvider(), api_key="k", model="m", messages=_messages()
    )
    assert "budget" in summary.lower()


# ── Reputation: needs_continuation gets partial, not full, credit ────────────
@requires_db
async def test_needs_continuation_scores_as_partial_not_success_or_pure_failure(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
        db.add(agent)
        await db.flush()
        run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=agent.id, goal="do a thing", status=TaskStatus.running, input={},
        )
        db.add(task)
        await db.commit()

        await task_svc.finalize(
            db, task=task, status=TaskStatus.needs_continuation,
            output={"summary": "got halfway there"},
        )
        await db.commit()

        assert task.status is TaskStatus.needs_continuation
        assert task.output["summary"] == "got halfway there"

        score = await reputation.get_or_create(db, company_id=company_id, agent_id=agent.id)
        assert score.reliability < 0.5  # not scored as a completed success
        assert 0.0 < score.accuracy < 1.0  # partial credit, not a flat 0 like a hard failure


# ── collect_results: an incomplete sub-task is surfaced, not silently dropped ─
@requires_db
async def test_collect_results_surfaces_needs_continuation_subtask(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    async with session_factory() as db:
        ceo = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
        worker = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
        db.add_all([ceo, worker])
        await db.flush()
        run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        parent = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=ceo.id, goal="oversee", status=TaskStatus.running, input={},
        )
        db.add(parent)
        await db.flush()
        child = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=worker.id, parent_task_id=parent.id, goal="research the market",
            status=TaskStatus.needs_continuation,
            output={"summary": "gathered three sources, ran out of steps"},
        )
        db.add(child)
        await db.commit()

        outcome = await _collect_results(db, None, agent=ceo, task=parent, args={})
        assert "Ran out of steps before finishing" in outcome.observation
        assert "research the market" in outcome.observation
        assert "gathered three sources" in outcome.observation
