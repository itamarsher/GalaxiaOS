"""Founder decision inbox: list pending, approve (resume task), reject (fail task)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Agent, DecisionRequest, MemoryEntry, Objective, Task
from app.models.enums import DecisionStatus, MemoryType, TaskStatus
from app.runtime.queue import enqueue_task
from app.schemas import DecisionOut, DecisionResolveRequest
from app.services import budget as budget_svc
from app.services import chat as chat_svc
from app.services import external_messages as ext

# Listing is company-scoped; resolve actions are by decision id (re-checked against membership).
router = APIRouter(tags=["decisions"])


async def _to_out(db, decisions: list[DecisionRequest]) -> list[DecisionOut]:
    """Enrich each decision with the bigger picture: who raised it, the ask that
    triggered it, and the objective it relates to — so the founder sees context
    before diving into the specifics."""
    agent_ids = {d.agent_id for d in decisions if d.agent_id}
    agents: dict = {}
    if agent_ids:
        agents = {
            a.id: a
            for a in (await db.scalars(select(Agent).where(Agent.id.in_(agent_ids)))).all()
        }

    # Load the triggering tasks (the "ask") plus their parent task (the initiative).
    task_ids = {d.task_id for d in decisions if d.task_id}
    tasks: dict = {}
    if task_ids:
        tasks = {
            t.id: t
            for t in (await db.scalars(select(Task).where(Task.id.in_(task_ids)))).all()
        }
    parent_ids = {t.parent_task_id for t in tasks.values() if t.parent_task_id}
    parents: dict = {}
    if parent_ids:
        parents = {
            t.id: t
            for t in (await db.scalars(select(Task).where(Task.id.in_(parent_ids)))).all()
        }

    # Objective linkage is explicit: a task carries the objective_id the CEO tagged
    # it with, so we just look the title up by id (no keyword guessing).
    objective_ids = {t.objective_id for t in tasks.values() if t.objective_id}
    objective_titles: dict = {}
    if objective_ids:
        objective_titles = {
            o.id: o.title
            for o in (
                await db.scalars(select(Objective).where(Objective.id.in_(objective_ids)))
            ).all()
        }

    out = []
    for d in decisions:
        item = DecisionOut.model_validate(d)
        agent = agents.get(d.agent_id)
        item.agent_name = agent.name if agent else None
        item.agent_role = agent.role.value if agent else None

        task = tasks.get(d.task_id) if d.task_id else None
        if task is not None:
            item.task_goal = task.goal
            parent = parents.get(task.parent_task_id) if task.parent_task_id else None
            # The initiative is the parent task's goal (the higher-level work the
            # CEO dispatched); a root task is its own initiative.
            item.initiative = parent.goal if parent is not None else task.goal
            item.objective_title = objective_titles.get(task.objective_id)
        out.append(item)
    return out


@router.get("/companies/{company_id}/decisions", response_model=list[DecisionOut])
async def list_decisions(company: CompanyDep, db: DbDep, only_pending: bool = True):
    stmt = (
        select(DecisionRequest)
        .where(DecisionRequest.company_id == company.id)
        .order_by(DecisionRequest.created_at.desc())
    )
    if only_pending:
        stmt = stmt.where(DecisionRequest.status == DecisionStatus.pending)
    return await _to_out(db, list((await db.scalars(stmt.limit(200))).all()))


async def _load_decision(db, user, decision_id: uuid.UUID) -> DecisionRequest:
    from app.models import Membership

    decision = await db.get(DecisionRequest, decision_id)
    if decision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found")
    member = await db.scalar(
        select(Membership).where(
            Membership.company_id == decision.company_id, Membership.user_id == user.id
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found")
    return decision


async def _apply_note(db, decision: DecisionRequest, note: str | None) -> None:
    """Persist the founder's guidance and surface it to the agent on resume.

    The note is stored on the decision and written to company memory so the
    re-running agent recalls it — letting the founder *modify* how the action is
    carried out, not just approve/reject it.
    """
    note = (note or "").strip()
    if not note:
        return
    decision.payload = {**(decision.payload or {}), "founder_note": note}
    await db.execute(
        MemoryEntry.__table__.insert().values(
            company_id=decision.company_id,
            type=MemoryType.decision,
            title=f"Founder guidance on: {decision.summary[:80]}",
            content=note,
        )
    )


def _ack_note(decision: DecisionRequest, *, note: str | None) -> str:
    """The directive that makes a resuming agent acknowledge the founder's decision.

    Stored on ``task.input['founder_ack']`` and surfaced once on resume (see
    ``NativeBackend._inject_resume_notes``): an agent that escalated to the founder
    and is now unparked by an approval should confirm back in the DM *before* it
    carries out the approved action — so a founder who answers always gets an
    immediate acknowledgment, not silence while the agent works.
    """
    note = (note or "").strip()
    tail = f' They added a note: "{note[:400]}".' if note else ""
    return (
        f'The founder APPROVED your request: "{decision.summary[:200]}".{tail} '
        + chat_svc.FOUNDER_ACK_DIRECTIVE
    )


def _reject_note(decision: DecisionRequest, *, note: str | None) -> str:
    """The directive a resuming agent gets when the founder DECLINES its request.

    A rejection no longer kills the task: it resumes so the agent can acknowledge
    and adapt (the concrete action stays blocked — see ``consume_rejection_grant``).
    This tells it what was declined, the founder's reason, and to confirm back and
    take a different path rather than silently stopping or re-requesting the same
    thing.
    """
    note = (note or "").strip()
    tail = f' Their reason: "{note[:400]}".' if note else ""
    return (
        f'The founder DECLINED your request: "{decision.summary[:200]}".{tail} '
        "Do not carry out that action or re-request it unchanged — adapt: take a "
        "different approach, or ask them a clarifying follow-up. "
        + chat_svc.FOUNDER_ACK_DIRECTIVE
    )


async def _post_resolution_dm(
    db, decision: DecisionRequest, *, resolution: str, note: str | None
) -> None:
    """Post the founder's verdict back into the decision's DM thread.

    Keeps the consolidated chat view honest: a structured decision surfaced as a
    founder DM gets a closing message when it's approved/rejected, so the thread
    reflects the outcome instead of going silent.
    """
    if decision.channel_id is None:
        return
    mark = "✅ Approved" if resolution == "approved" else "❌ Rejected"
    body = f"{mark}." + (f" {note.strip()}" if (note or "").strip() else "")
    await chat_svc.post_system_reply(
        db, company_id=decision.company_id, channel_id=decision.channel_id, body=body
    )


@router.post("/decisions/{decision_id}/approve", response_model=DecisionOut)
async def approve(
    decision_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    body: DecisionResolveRequest | None = Body(default=None),
):
    decision = await _load_decision(db, user, decision_id)
    decision.status = DecisionStatus.approved
    decision.resolved_by_user_id = user.id
    decision.resolved_at = datetime.now(UTC)
    await _apply_note(db, decision, body.note if body else None)
    await _post_resolution_dm(db, decision, resolution="approved", note=body.note if body else None)

    # Over-budget approvals carry the shortfall: authorising the spend lifts the
    # budget ceiling by that amount so the action goes through on resume. (The
    # actual top-up payment is wired in separately — this just clears the cap.)
    increase = int((decision.payload or {}).get("budget_increase_cents") or 0)
    if increase > 0:
        await budget_svc.increase_limit(
            db, company_id=decision.company_id, additional_cents=increase
        )

    resumed_task_id: uuid.UUID | None = None
    if decision.task_id:
        task = await db.get(Task, decision.task_id)
        # ``running`` is accepted alongside ``waiting_approval`` to recover tasks
        # that an earlier bug parked without flipping their status off ``running``.
        if task is not None and task.status in (
            TaskStatus.waiting_approval,
            TaskStatus.running,
        ):
            task.status = TaskStatus.queued
            resumed_task_id = task.id
            # When the escalation was surfaced in the agent↔founder DM, have the
            # resuming agent confirm back there first — an approval is the founder
            # replying, and they should hear "got it, doing X" right away.
            if decision.channel_id is not None:
                task.input = {
                    **(task.input or {}),
                    "founder_ack": _ack_note(decision, note=body.note if body else None),
                }
    await db.commit()
    if resumed_task_id is not None:
        await enqueue_task(resumed_task_id)
    return (await _to_out(db, [decision]))[0]


@router.post("/decisions/{decision_id}/reject", response_model=DecisionOut)
async def reject(
    decision_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    body: DecisionResolveRequest | None = Body(default=None),
):
    decision = await _load_decision(db, user, decision_id)
    decision.status = DecisionStatus.rejected
    decision.resolved_by_user_id = user.id
    decision.resolved_at = datetime.now(UTC)
    await _apply_note(db, decision, body.note if body else None)
    await _post_resolution_dm(db, decision, resolution="rejected", note=body.note if body else None)
    # If this gated an outbound message, mark its indexed record rejected so the
    # communications log shows it was never sent.
    await ext.mark_decision_resolved(db, decision_id=decision.id, approved=False)
    resumed_task_id: uuid.UUID | None = None
    if decision.task_id:
        task = await db.get(Task, decision.task_id)
        if task is not None and task.status in (
            TaskStatus.waiting_approval,
            TaskStatus.running,
        ):
            # A rejection is the founder replying "no", not a dead end: resume the
            # task so the agent acknowledges the decline and adapts (its transcript
            # is kept so it continues with context). The declined action itself
            # stays blocked at the gate (consume_rejection_grant).
            task.status = TaskStatus.queued
            resumed_task_id = task.id
            if decision.channel_id is not None:
                task.input = {
                    **(task.input or {}),
                    "founder_ack": _reject_note(decision, note=body.note if body else None),
                }
    await db.commit()
    if resumed_task_id is not None:
        await enqueue_task(resumed_task_id)
    return (await _to_out(db, [decision]))[0]
