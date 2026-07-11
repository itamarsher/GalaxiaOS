"""Tests for the independent self-validation critic.

Covers the vision plumbing (ImageBlock rendering in both providers), the critic
core (verdict parsing, metered vision/text calls, fail-open), the visual gate's
iterate-until-satisfied loop, and the devil's-advocate task-completion gate in the
native backend.
"""

from __future__ import annotations

import base64
import json

from app.models import Agent, AgentRun, Task
from app.models.enums import AgentRole, RunStatus, RunTrigger, TaskStatus
from app.providers import anthropic as anthropic_provider
from app.providers import openai as openai_provider
from app.providers.base import ImageBlock, LLMResponse, Message, TextBlock, Usage
from app.runtime import critic
from app.runtime.backends.native import NativeBackend
from app.runtime.tools.critique import visual_gate
from tests.conftest import requires_db

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")


# ── Vision plumbing: ImageBlock rendering ─────────────────────────────────────
def test_anthropic_renders_image_block():
    rendered = anthropic_provider._render_content(
        [TextBlock(text="look"), ImageBlock(data=_PNG, media_type="image/png")]
    )
    assert rendered[0] == {"type": "text", "text": "look"}
    assert rendered[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": _PNG},
    }


def test_openai_renders_image_block_as_multimodal_user_turn():
    out = openai_provider._to_oai_messages(
        "sys",
        [Message(role="user", content=[TextBlock(text="look"), ImageBlock(data=_PNG, media_type="image/jpeg")])],
    )
    # system + one user turn whose content is a multimodal array.
    user = out[-1]
    assert user["role"] == "user"
    assert user["content"][0] == {"type": "text", "text": "look"}
    assert user["content"][1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{_PNG}"},
    }


def test_image_block_does_not_break_token_estimation():
    # Both flatteners must handle an image without raising and reserve some budget.
    msg = Message(role="user", content=[TextBlock(text="hi"), ImageBlock(data=_PNG)])
    assert len(anthropic_provider._message_text(msg)) > 100
    assert len(openai_provider._flatten(msg.content)) > 100


# ── Verdict parsing ───────────────────────────────────────────────────────────
def test_parse_verdict_valid():
    v = critic._parse_verdict(
        json.dumps({"approved": False, "score": 3, "issues": ["cramped", "low contrast"], "revision": "add whitespace"})
    )
    assert v is not None
    assert v.approved is False and v.score == 3
    assert v.issues == ["cramped", "low contrast"]
    assert "whitespace" in v.revision


def test_parse_verdict_rejects_garbage():
    assert critic._parse_verdict("not json") is None
    assert critic._parse_verdict(json.dumps({"score": 5})) is None  # missing 'approved'


def test_verdict_feedback_lists_issues_and_fix():
    v = critic.Verdict(approved=False, score=4, issues=["ugly header"], revision="use a hero image")
    fb = v.feedback()
    assert "NEEDS WORK" in fb and "ugly header" in fb and "hero image" in fb


# ── Critic core: metered calls, vision, fail-open (monkeypatched provider) ─────
class _FakeProvider:
    name = "fake"
    default_models = {"cheap": "c", "planner": "p", "strategic": "s"}


class _FakeCostMeter:
    """Records the run_llm call and returns a canned structured verdict."""

    def __init__(self, verdict: dict):
        self._verdict = verdict
        self.calls: list[dict] = []

    async def run_llm(self, provider, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse(text=json.dumps(self._verdict), usage=Usage(1, 1), model="p")


class _Ctx:
    def __init__(self, cost_meter, session_factory=None):
        self.cost_meter = cost_meter
        self.session_factory = session_factory
        self.enqueued: list = []

    async def enqueue_task(self, task_id, *, delay_seconds: float = 0):
        self.enqueued.append(task_id)


class _FakeAgent:
    def __init__(self, role=AgentRole.design):
        import uuid

        self.id = uuid.uuid4()
        self.role = role


class _FakeTask:
    def __init__(self, goal="Make a page", company_id=None, input=None):
        import uuid

        self.id = uuid.uuid4()
        self.company_id = company_id or uuid.uuid4()
        self.goal = goal
        self.input = input or {}


async def test_review_visual_sends_the_image(monkeypatch):
    meter = _FakeCostMeter({"approved": True, "score": 9, "issues": [], "revision": ""})

    async def _resolve(db, *, company_id):
        from app.services.apikeys import ResolvedProvider

        return ResolvedProvider(_FakeProvider(), "key", "byo", "fake")

    monkeypatch.setattr(critic.apikeys, "resolve_active_provider", _resolve)
    agent, task = _FakeAgent(), _FakeTask()
    verdict = await critic.review_visual(
        object(), _Ctx(meter), company_id=task.company_id, agent=agent, task=task,
        kind="marketing image", brief="a logo", image=(b"rawbytes", "image/png"),
    )
    assert verdict is not None and verdict.approved
    # The metered call carried an actual ImageBlock (vision), attributed to the task.
    sent = meter.calls[0]
    blocks = sent["messages"][0].content
    assert any(isinstance(b, ImageBlock) for b in blocks)
    assert sent["task_id"] == task.id and sent["agent_id"] == agent.id
    assert sent["json_schema"] is critic.CRITIC_VERDICT_SCHEMA


async def test_review_visual_page_uses_html_text(monkeypatch):
    meter = _FakeCostMeter({"approved": False, "score": 2, "issues": ["plain"], "revision": "style it"})

    async def _resolve(db, *, company_id):
        from app.services.apikeys import ResolvedProvider

        return ResolvedProvider(_FakeProvider(), "key", "byo", "fake")

    monkeypatch.setattr(critic.apikeys, "resolve_active_provider", _resolve)
    agent, task = _FakeAgent(), _FakeTask()
    verdict = await critic.review_visual(
        object(), _Ctx(meter), company_id=task.company_id, agent=agent, task=task,
        kind="landing page", brief="waitlist", html="<html><body><h1>Hi</h1></body></html>",
    )
    assert verdict is not None and verdict.approved is False
    blocks = meter.calls[0]["messages"][0].content
    assert all(isinstance(b, TextBlock) for b in blocks)  # no image for a page
    assert any("<h1>Hi</h1>" in b.text for b in blocks)


async def test_review_output_is_devils_advocate_text(monkeypatch):
    meter = _FakeCostMeter({"approved": False, "score": 4, "issues": ["vague"], "revision": "be concrete"})

    async def _resolve(db, *, company_id):
        from app.services.apikeys import ResolvedProvider

        return ResolvedProvider(_FakeProvider(), "key", "byo", "fake")

    monkeypatch.setattr(critic.apikeys, "resolve_active_provider", _resolve)
    agent, task = _FakeAgent(AgentRole.growth), _FakeTask(goal="Grow signups")
    verdict = await critic.review_output(
        object(), _Ctx(meter), company_id=task.company_id, agent=agent, task=task,
        output={"summary": "did some stuff"},
    )
    assert verdict is not None and not verdict.approved
    assert "Grow signups" in meter.calls[0]["messages"][0].content[0].text


async def test_review_output_skips_empty_summary(monkeypatch):
    meter = _FakeCostMeter({"approved": True, "score": 8, "issues": [], "revision": ""})

    async def _resolve(db, *, company_id):
        from app.services.apikeys import ResolvedProvider

        return ResolvedProvider(_FakeProvider(), "key", "byo", "fake")

    monkeypatch.setattr(critic.apikeys, "resolve_active_provider", _resolve)
    v = await critic.review_output(
        object(), _Ctx(meter), company_id=None, agent=_FakeAgent(), task=_FakeTask(),
        output={"summary": ""},
    )
    assert v is None and meter.calls == []  # nothing to critique → no spend


async def test_critic_fails_open_without_provider(monkeypatch):
    async def _resolve(db, *, company_id):
        return None

    monkeypatch.setattr(critic.apikeys, "resolve_provider", _resolve)
    v = await critic.review_visual(
        object(), _Ctx(_FakeCostMeter({})), company_id=None, agent=_FakeAgent(), task=_FakeTask(),
        kind="marketing image", brief="x", image=(b"x", "image/png"),
    )
    assert v is None  # no key → skip, never block the agent


# ── DB-backed: visual gate loop + native task-completion critic ────────────────
async def _agent_and_task(session_factory, company_id, role=AgentRole.design):
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=role, name=role.value)
        db.add(agent)
        await db.flush()
        run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=agent.id, goal="make a thing", status=TaskStatus.running, input={},
        )
        db.add(task)
        await db.commit()
        return agent, task


@requires_db
async def test_visual_gate_iterates_then_passes(session_factory, company_with_budget, monkeypatch):
    """A rejected visual holds and bumps the round counter; an approval lets it through."""
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id)

    verdicts = iter([
        critic.Verdict(approved=False, score=3, issues=["cramped"], revision="add whitespace"),
        critic.Verdict(approved=True, score=9, issues=[], revision=""),
    ])

    async def _review(*a, **k):
        return next(verdicts)

    monkeypatch.setattr(critic, "review_visual", _review)
    ctx = _Ctx(_FakeCostMeter({}))

    async with session_factory() as db:
        hold = await visual_gate(
            db, ctx, agent=agent, task=task, key="image", kind="marketing image",
            brief="a logo", image=(b"x", "image/png"),
        )
        await db.commit()
    # First round: held for revision, counter incremented, artifact NOT accepted.
    assert hold is not None and "NOT ready" in hold.observation
    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert row.input["visual_rounds"]["image"] == 1

    async with session_factory() as db:
        row = await db.get(Task, task.id)
        task.input = row.input  # carry the counter forward as the loop would
        hold2 = await visual_gate(
            db, ctx, agent=agent, task=task, key="image", kind="marketing image",
            brief="a logo", image=(b"x", "image/png"),
        )
        await db.commit()
    # Second round: critic approved → gate steps aside and clears the counter.
    assert hold2 is None
    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert "image" not in row.input.get("visual_rounds", {})


@requires_db
async def test_visual_gate_accepts_after_cap(session_factory, company_with_budget, monkeypatch):
    """After the round cap the gate stops holding and accepts the artifact as-is."""
    from app.config import settings

    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id)

    async def _always_reject(*a, **k):
        return critic.Verdict(approved=False, score=2, issues=["ugly"], revision="fix")

    monkeypatch.setattr(critic, "review_visual", _always_reject)
    ctx = _Ctx(_FakeCostMeter({}))

    # A single publish sequence: it holds for revision `visual_critic_max_rounds`
    # times, then on the next attempt accepts the artifact as-is (returns None).
    outcomes = []
    for _ in range(settings.visual_critic_max_rounds + 1):
        async with session_factory() as db:
            row = await db.get(Task, task.id)
            task.input = row.input or {}
            out = await visual_gate(
                db, ctx, agent=agent, task=task, key="page:landing_page",
                kind="landing page", brief="x", html="<h1>x</h1>",
            )
            await db.commit()
        outcomes.append(out)
    assert all(o is not None for o in outcomes[: settings.visual_critic_max_rounds])
    assert outcomes[-1] is None  # cap reached → accepted


@requires_db
async def test_task_critic_requeues_with_feedback(session_factory, company_with_budget, monkeypatch):
    """An unhappy devil's-advocate critic re-queues the task with feedback injected."""
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id, role=AgentRole.growth)

    async def _review(*a, **k):
        return critic.Verdict(approved=False, score=4, issues=["thin"], revision="add detail")

    monkeypatch.setattr(critic, "review_output", _review)
    ctx = _Ctx(_FakeCostMeter({}), session_factory=session_factory)

    requeued = await NativeBackend()._maybe_critique(ctx, agent, task, {"summary": "did a bit"})
    assert requeued is True
    assert task.id in ctx.enqueued
    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.queued
        assert row.input["critic_rounds"] == 1
        assert "add detail" in row.input["critic_feedback"]


@requires_db
async def test_task_critic_approves_lets_it_finish(session_factory, company_with_budget, monkeypatch):
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id, role=AgentRole.growth)

    async def _review(*a, **k):
        return critic.Verdict(approved=True, score=9, issues=[], revision="")

    monkeypatch.setattr(critic, "review_output", _review)
    ctx = _Ctx(_FakeCostMeter({}), session_factory=session_factory)
    requeued = await NativeBackend()._maybe_critique(ctx, agent, task, {"summary": "solid"})
    assert requeued is False


@requires_db
async def test_task_critic_respects_round_cap_and_skips_reviews(
    session_factory, company_with_budget, monkeypatch
):
    from app.config import settings

    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id, role=AgentRole.growth)

    called = {"n": 0}

    async def _review(*a, **k):
        called["n"] += 1
        return critic.Verdict(approved=False, score=1, issues=["x"], revision="y")

    monkeypatch.setattr(critic, "review_output", _review)
    ctx = _Ctx(_FakeCostMeter({}), session_factory=session_factory)

    # At the cap → no critique, no requeue.
    task.input = {"critic_rounds": settings.critic_max_rounds}
    assert await NativeBackend()._maybe_critique(ctx, agent, task, {"summary": "s"}) is False
    # A CEO audit / failure-review task is never second-guessed by the critic.
    task.input = {"audit_target_task_id": "x"}
    assert await NativeBackend()._maybe_critique(ctx, agent, task, {"summary": "s"}) is False
    task.input = {"failure_review": True}
    assert await NativeBackend()._maybe_critique(ctx, agent, task, {"summary": "s"}) is False
    assert called["n"] == 0  # short-circuited before any LLM call


@requires_db
async def test_inject_feedback_surfaces_both_audit_and_critic(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id)
    async with session_factory() as db:
        row = await db.get(Task, task.id)
        row.input = {"audit_feedback": "CEO says fix scope", "critic_feedback": "Critic says add detail"}
        await db.commit()
        task.input = row.input

    ctx = _Ctx(_FakeCostMeter({}), session_factory=session_factory)
    messages = [Message(role="user", content="original goal")]
    await NativeBackend()._inject_resume_notes(ctx, task, messages)

    injected = messages[-1].content
    texts = " ".join(b.text for b in injected if isinstance(b, TextBlock))
    assert "CEO says fix scope" in texts and "Critic says add detail" in texts
    # Both notes are consumed so they inject only once.
    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert "audit_feedback" not in (row.input or {})
        assert "critic_feedback" not in (row.input or {})
