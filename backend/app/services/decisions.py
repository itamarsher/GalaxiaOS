"""Resolving founder decisions — the logic shared by every surface that can
approve or reject a :class:`DecisionRequest`.

Two callers use this:

* the HTTP endpoints in :mod:`app.api.decisions` (the game's swipe deck still
  resolves with an explicit approve/reject click), and
* the chat reply path (:func:`try_resolve_from_reply`), where the decision widget
  has been removed and the founder resolves a structured decision simply by
  replying in the DM — the reply is classified into approve/reject and routed
  through the exact same resolution as a button click.

Keeping the resolution in one place means the two surfaces stay behaviourally
identical: same memory write, same resume directive, same budget top-up.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import DecisionRequest, Task
from app.models.enums import DecisionStatus, MemoryType, TaskStatus
from app.providers.base import Message
from app.runtime.cost_meter import CostMeter
from app.services import apikeys
from app.services import budget as budget_svc
from app.services import chat as chat_svc
from app.services import external_messages as ext
from app.services import memory as memory_svc


async def _apply_note(db: AsyncSession, decision: DecisionRequest, note: str | None) -> None:
    """Persist the founder's guidance and surface it to the agent on resume.

    The note is stored on the decision and written to company memory so the
    re-running agent recalls it — letting the founder *modify* how the action is
    carried out, not just approve/reject it.

    The memory write goes through :func:`memory_svc.write` (not a raw insert) so the
    entry is embedded inline. Otherwise it lands with ``embedding = NULL`` and the
    CEO's next-cycle semantic recall — which filters on ``embedding IS NOT NULL`` —
    never surfaces the founder's feedback.
    """
    note = (note or "").strip()
    if not note:
        return
    decision.payload = {**(decision.payload or {}), "founder_note": note}
    await memory_svc.write(
        db,
        company_id=decision.company_id,
        type=MemoryType.decision,
        title=f"Founder guidance on: {decision.summary[:80]}",
        content=note,
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
    db: AsyncSession, decision: DecisionRequest, *, approved: bool, note: str | None
) -> None:
    """Post the founder's verdict back into the decision's DM thread.

    Keeps the consolidated chat view honest: a structured decision surfaced as a
    founder DM gets a closing message when it's approved/rejected, so the thread
    reflects the outcome instead of going silent.
    """
    if decision.channel_id is None:
        return
    mark = "✅ Approved" if approved else "❌ Rejected"
    body = f"{mark}." + (f" {note.strip()}" if (note or "").strip() else "")
    await chat_svc.post_system_reply(
        db, company_id=decision.company_id, channel_id=decision.channel_id, body=body
    )


async def resolve_decision(
    db: AsyncSession,
    decision: DecisionRequest,
    *,
    approved: bool,
    user_id: uuid.UUID | None,
    note: str | None,
) -> uuid.UUID | None:
    """Apply a founder approve/reject to a pending decision and resume its task.

    Mutates ``decision`` (and its task) in place; the caller commits and enqueues
    the returned task id (``None`` when there was nothing to resume). Shared by the
    HTTP endpoints and the chat reply path so both resolve identically.
    """
    decision.status = DecisionStatus.approved if approved else DecisionStatus.rejected
    decision.resolved_by_user_id = user_id
    decision.resolved_at = datetime.now(UTC)
    await _apply_note(db, decision, note)
    await _post_resolution_dm(db, decision, approved=approved, note=note)

    if approved:
        # Over-budget approvals carry the shortfall: authorising the spend lifts the
        # budget ceiling by that amount so the action goes through on resume. (The
        # actual top-up payment is wired in separately — this just clears the cap.)
        increase = int((decision.payload or {}).get("budget_increase_cents") or 0)
        if increase > 0:
            await budget_svc.increase_limit(
                db, company_id=decision.company_id, additional_cents=increase
            )
    else:
        # If this gated an outbound message, mark its indexed record rejected so the
        # communications log shows it was never sent.
        await ext.mark_decision_resolved(db, decision_id=decision.id, approved=False)

    if not decision.task_id:
        return None
    task = await db.get(Task, decision.task_id)
    # ``running`` is accepted alongside ``waiting_approval`` to recover tasks that an
    # earlier bug parked without flipping their status off ``running``.
    if task is None or task.status not in (TaskStatus.waiting_approval, TaskStatus.running):
        return None
    # A resolution is the founder replying: resume so the agent acknowledges and,
    # on approval, proceeds — on rejection, adapts. The declined action itself stays
    # blocked at the gate (consume_rejection_grant); its transcript is kept.
    task.status = TaskStatus.queued
    if decision.channel_id is not None:
        ack = _ack_note(decision, note=note) if approved else _reject_note(decision, note=note)
        task.input = {**(task.input or {}), "founder_ack": ack}
    return task.id


# --- Resolving from a plain chat reply -------------------------------------

_CLASSIFY_SYSTEM = (
    "An autonomous agent asked the company's founder to approve a specific action. "
    "You are given that request and the founder's free-text reply. Decide what the "
    "founder wants:\n"
    '- "approve": they clearly agree / grant it / say go ahead.\n'
    '- "reject": they clearly decline / say no / object / want it stopped or changed.\n'
    '- "unclear": they ask a question, need more info, or the reply is off-topic and '
    "does not settle the request.\n"
    "Judge the founder's intent toward THIS request, not general sentiment. When in "
    'doubt between a verdict and "unclear", choose "unclear".'
)

_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "reject", "unclear"]},
    },
    "required": ["verdict"],
}


async def _classify_reply(
    db: AsyncSession, *, company_id: uuid.UUID, summary: str, reply: str
) -> str:
    """Classify a founder's reply to a pending decision as approve/reject/unclear.

    Uses the company's cheap model. Any failure (no provider, budget exhausted,
    provider error, malformed output) degrades to ``"unclear"`` so a reply is never
    mis-resolved — the decision simply stays pending and the reply is treated as an
    ordinary message.
    """
    resolved = await apikeys.resolve_active_provider(db, company_id=company_id)
    if resolved is None:
        return "unclear"
    provider, api_key = resolved.provider, resolved.api_key
    meter = CostMeter(SessionLocal)
    try:
        resp = await meter.run_llm(
            provider,
            api_key=api_key,
            company_id=company_id,
            agent_id=None,
            task_id=None,
            model=provider.default_models["cheap"],
            system=_CLASSIFY_SYSTEM,
            messages=[
                Message(
                    role="user",
                    content=f"Request the founder was asked to approve:\n{summary}\n\nFounder's reply:\n{reply}",
                )
            ],
            max_tokens=64,
            json_schema=_CLASSIFY_SCHEMA,
            funding_user_id=resolved.funding_user_id,
        )
        verdict = json.loads(resp.text).get("verdict")
    except Exception:
        return "unclear"
    return verdict if verdict in ("approve", "reject") else "unclear"


async def try_resolve_from_reply(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    channel_id: uuid.UUID,
    reply: str,
    user_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Resolve the newest pending decision on a channel from the founder's reply.

    Returns the resumed task id to enqueue when the reply settled the decision, or
    ``None`` — meaning either there was no pending decision, or the reply was a
    question/aside (``"unclear"``) and the decision stays open for the founder to
    answer again. Decisions live on the channel's main timeline, so only call this
    for a main-timeline reply (``thread_id is None``).
    """
    decision = await db.scalar(
        select(DecisionRequest)
        .where(
            DecisionRequest.channel_id == channel_id,
            DecisionRequest.status == DecisionStatus.pending,
        )
        .order_by(DecisionRequest.created_at.desc())
        .limit(1)
    )
    if decision is None or decision.task_id is None:
        return None
    verdict = await _classify_reply(
        db, company_id=company_id, summary=decision.summary, reply=reply
    )
    if verdict == "unclear":
        return None
    return await resolve_decision(
        db, decision, approved=(verdict == "approve"), user_id=user_id, note=reply
    )
