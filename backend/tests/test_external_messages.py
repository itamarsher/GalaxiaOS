"""External-communication indexing + the founder-approval policy guardrail."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Agent, AgentRun, DecisionRequest, Task
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    ExternalMessageStatus,
    PolicyEffect,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.services import external_messages as ext
from app.services import governance as gov
from app.services.governance import _matches
from tests.conftest import requires_db


# ── Pure-logic: classifier + policy matcher (no DB) ──────────────────────────
def test_external_comm_classifier_covers_outbound_tools():
    for tool in ("send_email", "publish_content", "schedule_social_post",
                 "run_ad_campaign", "send_notification"):
        assert ext.is_external_comm(tool) is True
    # Internal/world-read tools are not external communications.
    for tool in ("write_memory", "web_search", "register_domain", "dispatch_task"):
        assert ext.is_external_comm(tool) is False


def test_describe_lifts_email_fields():
    d = ext.describe("send_email", {"to": "a@b.co", "subject": "Hi", "body": "Hello there"})
    assert d == {"channel": "email", "recipient": "a@b.co", "subject": "Hi", "body": "Hello there"}


def test_summarize_includes_recipient_and_body():
    md = ext.summarize("send_email", {"to": "a@b.co", "subject": "Hi", "body": "Buy now"})
    assert "a@b.co" in md and "Hi" in md and "Buy now" in md


def test_is_external_rule_matches_only_external_actions():
    rule = {"is_external": True}
    assert _matches(rule, {"tool": "send_email", "is_external": True}) is True
    assert _matches(rule, {"tool": "write_memory", "is_external": False}) is False
    # Missing key is treated as not-external.
    assert _matches(rule, {"tool": "write_memory"}) is False


# ── DB: the approval toggle drives the policy engine ─────────────────────────
@requires_db
async def test_toggle_gates_external_actions_via_evaluate(session_factory, company_with_budget):
    company_id = company_with_budget
    external = {"tool": "send_email", "agent_role": "growth", "is_external": True}
    internal = {"tool": "write_memory", "agent_role": "growth", "is_external": False}

    async with session_factory() as db:
        # Off by default: nothing seeded, so external sends are allowed.
        assert await gov.get_external_comms_approval(db, company_id=company_id) is False
        assert await gov.evaluate(db, company_id=company_id, action=external) is PolicyEffect.allow

        # Enabling the guardrail forces approval on every outbound message …
        await gov.set_external_comms_approval(db, company_id=company_id, enabled=True)
        await db.commit()

    async with session_factory() as db:
        assert await gov.get_external_comms_approval(db, company_id=company_id) is True
        assert (
            await gov.evaluate(db, company_id=company_id, action=external)
            is PolicyEffect.require_approval
        )
        # … but leaves internal tools untouched.
        assert await gov.evaluate(db, company_id=company_id, action=internal) is PolicyEffect.allow

        # Toggling it back off restores the open path (idempotent, no dup rows).
        await gov.set_external_comms_approval(db, company_id=company_id, enabled=False)
        await db.commit()

    async with session_factory() as db:
        assert await gov.evaluate(db, company_id=company_id, action=external) is PolicyEffect.allow
        from app.models import Policy

        rows = (
            await db.scalars(
                select(Policy).where(
                    Policy.company_id == company_id,
                    Policy.name == gov.EXTERNAL_COMMS_APPROVAL_POLICY,
                )
            )
        ).all()
        assert len(rows) == 1


# ── DB: indexing records every attempt and finalize avoids duplicates ────────
async def _make_task(session_factory, company_id) -> tuple[uuid.UUID, uuid.UUID]:
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
            agent_id=agent.id, goal="reach out", status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()
        return agent.id, task.id


@requires_db
async def test_record_and_list_external_messages(session_factory, company_with_budget):
    company_id = company_with_budget
    agent_id, task_id = await _make_task(session_factory, company_id)
    async with session_factory() as db:
        await ext.record(
            db, company_id=company_id, agent_id=agent_id, task_id=task_id,
            tool="send_email", args={"to": "x@y.co", "subject": "S", "body": "B"},
            status=ExternalMessageStatus.sent, detail="sent via resend",
        )
        await db.commit()
    async with session_factory() as db:
        msgs = await ext.list_messages(db, company_id=company_id)
        assert len(msgs) == 1
        m = msgs[0]
        assert m.channel == "email" and m.recipient == "x@y.co"
        assert m.status is ExternalMessageStatus.sent
        # Status filter works.
        assert await ext.list_messages(
            db, company_id=company_id, status=ExternalMessageStatus.blocked
        ) == []


@requires_db
async def test_finalize_resolves_parked_message_in_place(session_factory, company_with_budget):
    """The approve→resume path flips the pending row to sent, not a duplicate."""
    company_id = company_with_budget
    agent_id, task_id = await _make_task(session_factory, company_id)
    args = {"to": "x@y.co", "subject": "S", "body": "B"}

    async with session_factory() as db:
        await ext.record(
            db, company_id=company_id, agent_id=agent_id, task_id=task_id,
            tool="send_email", args=args, status=ExternalMessageStatus.pending_approval,
        )
        await db.commit()

    async with session_factory() as db:
        await ext.finalize(
            db, company_id=company_id, agent_id=agent_id, task_id=task_id,
            tool="send_email", args=args, sent=True, detail="sent via resend",
        )
        await db.commit()

    async with session_factory() as db:
        msgs = await ext.list_messages(db, company_id=company_id)
        assert len(msgs) == 1  # updated in place, not duplicated
        assert msgs[0].status is ExternalMessageStatus.sent


@requires_db
async def test_finalize_inserts_when_no_parked_row(session_factory, company_with_budget):
    company_id = company_with_budget
    agent_id, task_id = await _make_task(session_factory, company_id)
    async with session_factory() as db:
        await ext.finalize(
            db, company_id=company_id, agent_id=agent_id, task_id=task_id,
            tool="send_email", args={"to": "x@y.co", "subject": "S", "body": "B"},
            sent=False, detail="provider error",
        )
        await db.commit()
    async with session_factory() as db:
        msgs = await ext.list_messages(db, company_id=company_id)
        assert len(msgs) == 1 and msgs[0].status is ExternalMessageStatus.failed


@requires_db
async def test_reject_marks_parked_message_rejected(session_factory, company_with_budget):
    company_id = company_with_budget
    agent_id, task_id = await _make_task(session_factory, company_id)
    async with session_factory() as db:
        decision = DecisionRequest(
            company_id=company_id, agent_id=agent_id, task_id=task_id,
            kind=DecisionKind.external_comm, summary="approve send",
            payload={"tool": "send_email", "args": {}}, status=DecisionStatus.pending,
        )
        db.add(decision)
        await db.flush()
        await ext.record(
            db, company_id=company_id, agent_id=agent_id, task_id=task_id,
            tool="send_email", args={"to": "x@y.co"},
            status=ExternalMessageStatus.pending_approval, decision_id=decision.id,
        )
        await db.commit()
        decision_id = decision.id

    async with session_factory() as db:
        await ext.mark_decision_resolved(db, decision_id=decision_id, approved=False)
        await db.commit()

    async with session_factory() as db:
        msgs = await ext.list_messages(db, company_id=company_id)
        assert msgs[0].status is ExternalMessageStatus.rejected


@requires_db
async def test_recently_rejected_outbound_is_company_scoped(session_factory, company_with_budget):
    """A founder rejection of an outbound blocks the SAME target from re-escalating.

    Guards the resubmit loop: the per-task grant only stops one task, so a landing
    page the founder declined would otherwise be re-proposed by the next task/cycle.
    ``recently_rejected_outbound`` is the company-scoped memory that stops it.
    """
    company_id = company_with_budget
    agent_id, task_id = await _make_task(session_factory, company_id)

    async with session_factory() as db:
        db.add(
            DecisionRequest(
                company_id=company_id,
                agent_id=agent_id,
                task_id=task_id,
                kind=DecisionKind.external_comm,
                summary="landing page",
                payload={
                    "tool": "publish_content",
                    "args": {"channel": "landing_page", "title": "v1", "body": "..."},
                    "founder_note": "Not until we have demand evidence.",
                },
                status=DecisionStatus.rejected,
            )
        )
        await db.commit()

    async with session_factory() as db:
        # A DIFFERENT task re-attempting the same landing page is caught (company-scoped),
        # and the founder's note comes back so the agent can adapt.
        hit = await ext.recently_rejected_outbound(
            db, company_id=company_id, tool="publish_content",
            args={"channel": "landing_page", "title": "v1 (reworded)", "body": "..."},
            within_minutes=180,
        )
        assert hit is not None
        assert hit.payload["founder_note"] == "Not until we have demand evidence."

        # A different channel (email to someone) is NOT blocked by a rejected page.
        assert await ext.recently_rejected_outbound(
            db, company_id=company_id, tool="send_email",
            args={"to": "x@y.co", "subject": "Hi", "body": "..."}, within_minutes=180,
        ) is None

        # And the window bounds it: a 0-minute cooldown disables the guard entirely.
        assert await ext.recently_rejected_outbound(
            db, company_id=company_id, tool="publish_content",
            args={"channel": "landing_page"}, within_minutes=0,
        ) is None
