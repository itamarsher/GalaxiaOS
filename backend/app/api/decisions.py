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
from app.schemas import (
    DecisionChatRequest,
    DecisionChatResult,
    DecisionChatThread,
    DecisionChatTurn,
    DecisionOut,
    DecisionResolveRequest,
)
from app.services import budget as budget_svc
from app.services import copilot, memory

# Listing is company-scoped; resolve actions are by decision id (re-checked against membership).
router = APIRouter(tags=["decisions"])


# Words too generic to signal which objective a task belongs to.
_STOPWORDS = frozenset(
    """
    the and for with that this from your you our are will into them they then than
    have has had who what when where which while about over under above below
    company business mission objective objectives plan agent agents task work
    initiative initiatives founder approve approval budget spend decision goal
    """.split()
)


def _keywords(*texts: str | None) -> set[str]:
    words: set[str] = set()
    for text in texts:
        for raw in (text or "").lower().replace("/", " ").split():
            token = "".join(ch for ch in raw if ch.isalnum())
            if len(token) >= 4 and token not in _STOPWORDS:
                words.add(token)
    return words


def _best_objective(text_words: set[str], objectives: list[Objective]) -> str | None:
    """Best-effort link a decision's context to an objective by keyword overlap.

    Tasks carry no explicit objective foreign key, so we pick the objective whose
    title/rationale shares the most distinctive words with the triggering ask.
    Requires at least two overlapping words so a weak coincidence isn't surfaced
    as the "related objective".
    """
    best: tuple[int, str] | None = None
    for obj in objectives:
        overlap = len(text_words & _keywords(obj.title, obj.rationale))
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, obj.title)
    return best[1] if best else None


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

    # Objectives per company, for best-effort objective linkage.
    company_ids = {d.company_id for d in decisions}
    objectives: dict = {}
    if company_ids:
        for o in (
            await db.scalars(select(Objective).where(Objective.company_id.in_(company_ids)))
        ).all():
            objectives.setdefault(o.company_id, []).append(o)

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
            item.objective_title = _best_objective(
                _keywords(task.goal, parent.goal if parent else None, d.summary),
                objectives.get(d.company_id, []),
            )
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


@router.get("/decisions/{decision_id}/chat", response_model=DecisionChatThread)
async def chat_thread(decision_id: uuid.UUID, db: DbDep, user: CurrentUser):
    """The persisted discussion thread for a decision (for loading on open/reload)."""
    decision = await _load_decision(db, user, decision_id)
    return DecisionChatThread(thread=_load_thread(decision))


@router.post("/decisions/{decision_id}/chat", response_model=DecisionChatResult)
async def chat(
    decision_id: uuid.UUID, body: DecisionChatRequest, db: DbDep, user: CurrentUser
):
    """Discuss a decision with the agent that raised it.

    The thread is persisted on the decision, so the agent answers with the full
    prior conversation in context and the founder keeps it across reloads.
    """
    decision = await _load_decision(db, user, decision_id)
    thread = _load_thread(decision)
    answer = await copilot.discuss_decision(
        db,
        company_id=decision.company_id,
        decision=decision,
        message=body.message,
        history=thread,
    )
    # Append this exchange and persist. Reassign (don't mutate in place) so
    # SQLAlchemy flags the JSONB column as dirty.
    updated = [*thread, DecisionChatTurn(who="you", text=body.message),
               DecisionChatTurn(who="agent", text=answer)]
    decision.chat = [t.model_dump() for t in updated]
    await db.commit()
    return DecisionChatResult(answer=answer, thread=updated)


def _load_thread(decision: DecisionRequest) -> list[DecisionChatTurn]:
    """Parse the persisted ``chat`` column into validated turns (oldest first)."""
    return [DecisionChatTurn(**t) for t in (decision.chat or []) if isinstance(t, dict)]


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


def _render_discussion(thread) -> str:
    """Render a stored chat thread as ``Founder:`` / ``Agent:`` lines."""
    lines = []
    for turn in thread or []:
        if not isinstance(turn, dict):
            continue
        text = (turn.get("text") or "").strip()
        if text:
            lines.append(f"{'Founder' if turn.get('who') == 'you' else 'Agent'}: {text}")
    return "\n".join(lines)


async def _apply_discussion(db, decision: DecisionRequest, *, resolution: str) -> None:
    """Surface the *entire* founder↔agent discussion to the agent on resume.

    Beyond the one-line guidance note, the whole back-and-forth from the Discuss
    panel is written to company memory (embedded, so it's recalled like other
    learnings), prefixed with how the founder ultimately resolved the decision —
    so the re-running agent acts with the full conversation in context.
    """
    rendered = _render_discussion(decision.chat)
    if not rendered:
        return
    await memory.write(
        db,
        company_id=decision.company_id,
        type=MemoryType.decision,
        title=f"Founder discussion ({resolution}) on: {decision.summary[:80]}",
        content=f"The founder {resolution} this decision after discussing it:\n{rendered}",
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
    await _apply_discussion(db, decision, resolution="approved")

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
    await _apply_discussion(db, decision, resolution="rejected")
    if decision.task_id:
        task = await db.get(Task, decision.task_id)
        if task is not None and task.status in (
            TaskStatus.waiting_approval,
            TaskStatus.running,
        ):
            task.status = TaskStatus.failed
            task.output = {"rejected": True}
            task.transcript = None  # terminal: drop the working-memory checkpoint
    await db.commit()
    return (await _to_out(db, [decision]))[0]
