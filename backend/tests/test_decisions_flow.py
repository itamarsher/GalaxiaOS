"""Regression tests for the founder decision / parking flow.

Guards the bug where ``request_decision`` mutated a session-detached ``Task`` and
so never persisted ``waiting_approval`` — leaving the task stuck in ``running``
even though it had escalated. Open-ended escalations are now consolidated into
chat: ``request_decision`` posts a founder DM and parks on a ``ChatWait`` instead
of creating a separate ``DecisionRequest`` (which now only backs structured,
grant-carrying decisions).
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Agent, AgentRun, ChatWait, DecisionRequest, Membership, Task, User
from app.models.enums import (
    AgentRole,
    ChatWaitStatus,
    DecisionKind,
    DecisionStatus,
    MembershipRole,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.providers.base import Message
from app.runtime.backends.native import NativeBackend, _consume_approval_grant
from app.runtime.tools import execute_tool
from app.services import chat
from tests.conftest import requires_db


async def _make_running_task(session_factory, company_id):
    """Create a task left in ``running`` and return it detached (session closed).

    This mirrors how the worker hands a task to the backend: it is loaded and
    committed as ``running`` in one session, which then closes, so the object the
    tool handler later receives is detached from the live DB session.
    """
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
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
        return agent, task  # detached once the `async with` block exits


@requires_db
async def test_request_decision_parks_detached_task(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _make_running_task(session_factory, company_id)

    # Invoke the tool exactly as NativeBackend._handle_call does: a fresh session,
    # with the detached agent/task objects.
    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="request_decision",
            args={"kind": "strategy", "summary": "need founder approval"},
        )
        await db.commit()
    assert outcome.park is True

    async with session_factory() as db:
        row = await db.get(Task, task.id)
        # The task must actually be parked in the DB (not silently left running).
        assert row.status is TaskStatus.waiting_approval
        # Open-ended decisions are now founder DMs: a ChatWait marks the wait and
        # the question is posted into the agent↔founder thread (no DecisionRequest).
        wait = await db.scalar(select(ChatWait).where(ChatWait.task_id == task.id))
        assert wait is not None and wait.status is ChatWaitStatus.pending
        channel = await chat.founder_dm(db, company_id=company_id, agent_id=agent.id)
        msgs = await chat.messages(db, channel_id=channel.id)
        assert any("need founder approval" in m.body for m in msgs)
        decisions = await db.scalar(
            select(func.count())
            .select_from(DecisionRequest)
            .where(DecisionRequest.task_id == task.id)
        )
        assert decisions == 0


@requires_db
async def test_submit_plan_is_idempotent_on_rerun(session_factory, company_with_budget):
    """Re-running a still-``running`` CEO task (e.g. after a restart) must not
    create a second plan_approval decision — the founder should see one plan."""
    company_id = company_with_budget
    agent, task = await _make_running_task(session_factory, company_id)

    async def _submit():
        async with session_factory() as db:
            outcome = await execute_tool(
                db,
                object(),
                agent=agent,
                task=task,
                name="submit_plan",
                args={"plan": "## Objective\n- ship the MVP"},
            )
            await db.commit()
            return outcome

    first = await _submit()
    # Second call mirrors the restart re-run: same task, plan already pending.
    second = await _submit()

    assert first.park is True
    assert second.park is True
    async with session_factory() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(DecisionRequest)
            .where(
                DecisionRequest.task_id == task.id,
                DecisionRequest.kind == DecisionKind.plan_approval,
                DecisionRequest.status == DecisionStatus.pending,
            )
        )
        # Exactly one pending plan_approval, not two.
        assert count == 1
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.waiting_approval


@requires_db
async def test_approval_grant_is_one_shot(session_factory, company_with_budget):
    """An approved decision lets the gated action proceed exactly once on resume."""
    company_id = company_with_budget
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
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
            status=TaskStatus.queued,
        )
        db.add(task)
        await db.flush()
        db.add(
            DecisionRequest(
                company_id=company_id,
                agent_id=agent.id,
                task_id=task.id,
                kind=DecisionKind.spend_approval,
                summary="Approve register_domain",
                payload={"tool": "register_domain", "args": {}},
                status=DecisionStatus.approved,
            )
        )
        await db.commit()
        task_id = task.id

    async with session_factory() as db:
        first = await _consume_approval_grant(db, task_id=task_id, tool="register_domain")
        second = await _consume_approval_grant(db, task_id=task_id, tool="register_domain")
        other = await _consume_approval_grant(db, task_id=task_id, tool="send_email")
        await db.commit()
        # Approved once -> allowed once; never re-escalates the same action, and a
        # different tool is not covered by this grant.
        assert first is True
        assert second is False
        assert other is False


@requires_db
async def test_approving_a_decision_makes_the_agent_acknowledge(
    session_factory, company_with_budget, monkeypatch
):
    """Approving a founder-DM decision unparks the agent WITH an acknowledgment
    directive, so the founder who just answered hears back immediately."""
    from app.api import decisions as decisions_api
    from app.schemas import DecisionResolveRequest

    # Don't reach for redis in a unit test — we only care about the DB state.
    async def _noop_enqueue(*args, **kwargs):
        return None

    monkeypatch.setattr(decisions_api, "enqueue_task", _noop_enqueue)

    company_id = company_with_budget
    async with session_factory() as db:
        user = User(email=f"{__import__('uuid').uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        db.add(Membership(company_id=company_id, user_id=user.id, role=MembershipRole.founder))
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
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
            status=TaskStatus.waiting_approval,
        )
        db.add(task)
        await db.flush()  # populate task.id before the decision references it
        decision = DecisionRequest(
            company_id=company_id,
            agent_id=agent.id,
            task_id=task.id,
            kind=DecisionKind.spend_approval,
            summary="Approve register_domain",
            payload={"tool": "register_domain", "args": {}},
            status=DecisionStatus.pending,
        )
        db.add(decision)
        await db.flush()
        # Structured decisions surface in the agent↔founder DM; that channel is
        # where the acknowledgment should land.
        await chat.attach_decision_dm(db, decision=decision)
        await db.commit()
        decision_id, task_id, user_id = decision.id, task.id, user.id

    async with session_factory() as db:
        row_user = await db.get(User, user_id)
        # No note here: the founder-note path writes to `memory_entries`, a table the
        # test schema intentionally omits. Note propagation is covered by the pure
        # `_ack_note` assertion below.
        await decisions_api.approve(decision_id, db, row_user, DecisionResolveRequest(note=None))

    async with session_factory() as db:
        row = await db.get(Task, task_id)
        # Task is unparked and carries a one-shot acknowledgment directive.
        assert row.status is TaskStatus.queued
        ack = (row.input or {}).get("founder_ack")
        assert ack is not None
        assert chat.FOUNDER_ACK_DIRECTIVE in ack
        assert "Approve register_domain" in ack

    # A founder note is folded into the acknowledgment (pure builder, no DB).
    async with session_factory() as db:
        decision = await db.get(DecisionRequest, decision_id)
    noted = decisions_api._ack_note(decision, note="Ship it, but log the spend.")
    assert "Ship it, but log the spend." in noted
    assert chat.FOUNDER_ACK_DIRECTIVE in noted

    # And that directive is actually surfaced to the resuming agent, then consumed.
    async with session_factory() as db:
        detached = await db.get(Task, task_id)  # expire_on_commit=False → usable detached
    messages = [Message(role="user", content="prior turn")]
    await NativeBackend()._inject_resume_notes(_AckCtx(session_factory), detached, messages)
    text = " ".join(getattr(b, "text", "") for b in messages[-1].content)
    assert chat.FOUNDER_ACK_DIRECTIVE in text
    async with session_factory() as db:
        row = await db.get(Task, task_id)
        assert "founder_ack" not in (row.input or {})


class _AckCtx:
    """Minimal RuntimeContext stand-in: the note injector only needs a session."""

    def __init__(self, session_factory):
        self.session_factory = session_factory


@requires_db
async def test_rejecting_a_decision_continues_the_task(
    session_factory, company_with_budget, monkeypatch
):
    """A rejection is not a dead end: the task resumes (queued, not failed) with a
    directive to acknowledge the decline and adapt."""
    from app.api import decisions as decisions_api
    from app.schemas import DecisionResolveRequest

    async def _noop_enqueue(*args, **kwargs):
        return None

    monkeypatch.setattr(decisions_api, "enqueue_task", _noop_enqueue)

    company_id = company_with_budget
    async with session_factory() as db:
        user = User(email=f"{__import__('uuid').uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        db.add(Membership(company_id=company_id, user_id=user.id, role=MembershipRole.founder))
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
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
            status=TaskStatus.waiting_approval,
            transcript=[{"role": "user", "content": "prior turn"}],
        )
        db.add(task)
        await db.flush()
        decision = DecisionRequest(
            company_id=company_id,
            agent_id=agent.id,
            task_id=task.id,
            kind=DecisionKind.external_comm,
            summary="Send launch email",
            payload={"tool": "send_email", "args": {"to": "x@y.co"}},
            status=DecisionStatus.pending,
        )
        db.add(decision)
        await db.flush()
        await chat.attach_decision_dm(db, decision=decision)
        await db.commit()
        decision_id, task_id, user_id = decision.id, task.id, user.id

    async with session_factory() as db:
        row_user = await db.get(User, user_id)
        await decisions_api.reject(decision_id, db, row_user, DecisionResolveRequest(note=None))

    async with session_factory() as db:
        row = await db.get(Task, task_id)
        # Continues instead of failing, keeps its context, and gets the adapt directive.
        assert row.status is TaskStatus.queued
        assert row.transcript is not None  # working memory kept for the resume
        note = (row.input or {}).get("founder_ack")
        assert note is not None
        assert chat.FOUNDER_ACK_DIRECTIVE in note
        assert "DECLINED" in note

    # The founder's reason is folded into the directive (pure builder, no DB).
    async with session_factory() as db:
        decision = await db.get(DecisionRequest, decision_id)
    noted = decisions_api._reject_note(decision, note="Too aggressive — soften the tone.")
    assert "Too aggressive — soften the tone." in noted


@requires_db
async def test_rejected_action_is_blocked_on_exact_retry(session_factory, company_with_budget):
    """A declined action stays blocked when re-issued verbatim, but the same tool
    with different args (an adapted attempt) is not."""
    from app.runtime.tools.base import consume_rejection_grant

    company_id = company_with_budget
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="G")
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
            agent_id=agent.id, goal="g", status=TaskStatus.queued,
        )
        db.add(task)
        await db.flush()
        db.add(
            DecisionRequest(
                company_id=company_id, agent_id=agent.id, task_id=task.id,
                kind=DecisionKind.external_comm, summary="Send it",
                payload={"tool": "send_email", "args": {"to": "x@y.co"}},
                status=DecisionStatus.rejected,
            )
        )
        await db.commit()
        task_id = task.id

    async with session_factory() as db:
        # A different action (other args) is NOT covered by this rejection.
        other = await consume_rejection_grant(
            db, task_id=task_id, tool="send_email", args={"to": "z@y.co"}
        )
        # The exact declined call is blocked once, then consumed (one-shot).
        first = await consume_rejection_grant(
            db, task_id=task_id, tool="send_email", args={"to": "x@y.co"}
        )
        second = await consume_rejection_grant(
            db, task_id=task_id, tool="send_email", args={"to": "x@y.co"}
        )
        await db.commit()
        assert other is None
        assert first is not None
        assert second is None
