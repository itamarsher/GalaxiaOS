"""Graceful handling of an exhausted LLM-provider balance.

BYOK means the founder's *own* provider account (Anthropic/OpenAI) pays for every
token. When that account runs dry the vendor refuses calls — Anthropic returns
"your credit balance is too low", OpenAI returns ``insufficient_quota`` — which
the provider layer surfaces as :class:`ProviderError` with
``kind == "insufficient_credits"`` (see :mod:`app.providers`). This is different
from the company's *internal* budget cap (:class:`app.services.budget.BudgetExceeded`,
which the founder can lift by approving a spend): here the money simply isn't
there, so **no agent work can run** until the founder tops up.

This module is the policy for that situation:

* :func:`handle_exhaustion` — the runtime calls this when a task hits the error.
  It pauses every in-flight task (queued/running → :attr:`TaskStatus.paused`,
  transcripts preserved) and raises a single :class:`DecisionRequest` from the
  CEO asking the founder to load more balance. Idempotent and serialized per
  company, so a burst of concurrent failures yields exactly one pause + one ask.
* :func:`attempt_resume` — called when the founder says they reloaded (approving
  the decision) and again on the periodic re-check. It **validates** the provider
  actually has balance now with a tiny probe call, and only then resumes the
  paused tasks. If the API still reports an empty balance it resurfaces to the
  founder and asks the caller to re-check again later.

The "company is balance-exhausted" state is simply *a pending
``provider_balance`` decision exists* (:func:`is_exhausted`) — durable in
Postgres, so it survives restarts and needs no extra column.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Company, DecisionRequest, Task
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    TaskStatus,
)
from app.providers.base import Message, ProviderError
from app.services import apikeys
from app.services import chat as chat_svc

#: The :class:`ProviderError.kind` the providers raise when the account is dry.
INSUFFICIENT_BALANCE_KIND = "insufficient_credits"

#: Task states that represent live, resumable work. These are flipped to
#: ``paused`` on exhaustion and back to ``queued`` on resume. ``waiting_approval``
#: and ``auditing`` are deliberately left alone — they're parked on *their own*
#: gate (a founder decision / a CEO audit), not actively burning the loop, so we
#: don't disturb those state machines.
_PAUSEABLE = (TaskStatus.queued, TaskStatus.running)


@dataclass
class ResumeOutcome:
    """Result of an :func:`attempt_resume` pass, for the caller to act on."""

    #: True when the balance was confirmed and the paused tasks were released.
    resumed: bool = False
    #: Task ids the caller should enqueue (the freshly un-paused tasks).
    resumed_task_ids: list[uuid.UUID] = field(default_factory=list)
    #: True while the provider still reports no balance — the caller should
    #: schedule another re-check (the 15-minute resurface).
    still_exhausted: bool = False


async def _lock_company(db: AsyncSession, company_id: uuid.UUID) -> Company | None:
    """Lock the company row to serialize concurrent exhaustion/resume handling."""
    return await db.scalar(
        select(Company).where(Company.id == company_id).with_for_update().limit(1)
    )


async def _pending_decision(
    db: AsyncSession, company_id: uuid.UUID
) -> DecisionRequest | None:
    """The open "please top up the provider balance" ask, if one exists."""
    return await db.scalar(
        select(DecisionRequest)
        .where(
            DecisionRequest.company_id == company_id,
            DecisionRequest.kind == DecisionKind.provider_balance,
            DecisionRequest.status == DecisionStatus.pending,
        )
        .order_by(DecisionRequest.created_at.desc())
        .limit(1)
    )


async def is_exhausted(db: AsyncSession, company_id: uuid.UUID) -> bool:
    """True if the company is currently paused for an empty provider balance.

    The single source of truth is an open ``provider_balance`` decision, so this
    is cheap and survives restarts. Used to gate the runtime (park new tasks
    rather than burn another failing call) and to stop continuation/cron from
    spinning up fresh work that would only hit the same wall.
    """
    return await _pending_decision(db, company_id) is not None


async def _ceo(db: AsyncSession, company_id: uuid.UUID) -> Agent | None:
    return await db.scalar(
        select(Agent).where(
            Agent.company_id == company_id, Agent.role == AgentRole.ceo
        )
    )


async def _pause_active_tasks(db: AsyncSession, company_id: uuid.UUID) -> list[uuid.UUID]:
    """Flip every live task to ``paused``; return the ids paused.

    Transcripts are left intact so each task resumes from its last checkpoint.
    """
    tasks = (
        await db.scalars(
            select(Task).where(
                Task.company_id == company_id, Task.status.in_(_PAUSEABLE)
            )
        )
    ).all()
    paused: list[uuid.UUID] = []
    for task in tasks:
        task.status = TaskStatus.paused
        paused.append(task.id)
    await db.flush()
    return paused


async def _resume_paused_tasks(db: AsyncSession, company_id: uuid.UUID) -> list[uuid.UUID]:
    """Flip every ``paused`` task back to ``queued``; return the ids to enqueue."""
    tasks = (
        await db.scalars(
            select(Task).where(
                Task.company_id == company_id, Task.status == TaskStatus.paused
            )
        )
    ).all()
    resumed: list[uuid.UUID] = []
    for task in tasks:
        task.status = TaskStatus.queued
        resumed.append(task.id)
    await db.flush()
    return resumed


def _exhaustion_summary(provider_name: str | None, paused_count: int) -> str:
    """The CEO's message to the founder explaining the pause and the ask."""
    who = f"our AI provider ({provider_name})" if provider_name else "our AI provider"
    return (
        "**⛔ Provider balance exhausted**\n\n"
        f"{who.capitalize()} is refusing API calls because the account's credit "
        "balance is too low. I've **paused all in-flight work** "
        f"({paused_count} task(s)) so nothing is lost.\n\n"
        "**Action needed:** please load more balance onto the provider account, "
        "then approve this so I can verify the balance and resume the team. If it "
        "still reads empty I'll check again in ~15 minutes and let you know."
    )


async def handle_exhaustion(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    provider_name: str | None = None,
) -> DecisionRequest | None:
    """Pause the fleet and ask the founder to top up — idempotently.

    Serialized on the company row so a flurry of concurrent ``insufficient_credits``
    failures produces exactly one pause + one founder ask. Returns the newly
    created :class:`DecisionRequest` on first detection, or ``None`` if the
    company was already flagged (in which case it just re-asserts the pause). The
    caller commits.
    """
    await _lock_company(db, company_id)

    # Always (re)assert the pause: a task that slipped through and started running
    # before the flag was set still gets parked here.
    paused = await _pause_active_tasks(db, company_id)

    existing = await _pending_decision(db, company_id)
    if existing is not None:
        return None

    ceo = await _ceo(db, company_id)
    decision = DecisionRequest(
        company_id=company_id,
        agent_id=ceo.id if ceo is not None else None,
        task_id=None,  # company-wide, not tied to a single task
        kind=DecisionKind.provider_balance,
        summary=_exhaustion_summary(provider_name, len(paused)),
        payload={"paused_task_ids": [str(t) for t in paused]},
        status=DecisionStatus.pending,
    )
    db.add(decision)
    await db.flush()
    # Surface it as a CEO → founder DM marked "waiting for a response".
    await chat_svc.attach_decision_dm(db, decision=decision)
    return decision


async def _has_balance(provider, *, api_key: str) -> bool:
    """Probe the provider with a minimal call to confirm the account can spend.

    Deliberately tiny (1 output token, no tools) — it's a health check, not agent
    work, so it isn't metered against the company budget. Returns ``False`` only
    for an ``insufficient_credits`` refusal; any other provider failure (network,
    auth, …) propagates so it isn't mistaken for "still out of money".
    """
    model = provider.default_models.get("cheap") or next(
        iter(provider.default_models.values())
    )
    try:
        await provider.complete(
            api_key=api_key,
            model=model,
            system="",
            messages=[Message(role="user", content="ping")],
            max_tokens=1,
        )
    except ProviderError as exc:
        if exc.kind == INSUFFICIENT_BALANCE_KIND:
            return False
        raise
    return True


async def _post_ceo_dm(db: AsyncSession, company_id: uuid.UUID, body: str) -> None:
    """Post a CEO status line into the founder DM (no-op without a CEO)."""
    ceo = await _ceo(db, company_id)
    if ceo is None:
        return
    await chat_svc.post_agent_dm(db, company_id=company_id, agent_id=ceo.id, body=body)


async def attempt_resume(
    db: AsyncSession, *, company_id: uuid.UUID
) -> ResumeOutcome:
    """Validate the provider balance and resume the fleet if it's healthy.

    Called both when the founder approves the top-up ask ("I reloaded") and on the
    periodic re-check. Self-terminating: if the company isn't flagged exhausted
    (already resumed by another pass) it no-ops. The caller commits, then enqueues
    :attr:`ResumeOutcome.resumed_task_ids` and — if
    :attr:`ResumeOutcome.still_exhausted` — schedules the next re-check.
    """
    await _lock_company(db, company_id)
    decision = await _pending_decision(db, company_id)
    if decision is None:
        # Nothing to do — another pass (or the founder) already cleared it.
        return ResumeOutcome()

    resolved = await apikeys.resolve_provider(db, company_id=company_id)
    if resolved is None:
        # Can't validate without a key. Stay paused and keep nudging.
        await _post_ceo_dm(
            db,
            company_id,
            "⚠️ I can't verify the provider balance — no API key is configured. "
            "Please add the provider key (and load balance), then approve again.",
        )
        return ResumeOutcome(still_exhausted=True)

    provider, api_key = resolved
    try:
        healthy = await _has_balance(provider, api_key=api_key)
    except ProviderError as exc:
        # A non-balance failure (bad key, network blip) — we can't confirm the
        # account, so stay paused and try again rather than resume blindly or crash
        # the caller. Surface why so the founder can act if it's their key.
        await _post_ceo_dm(
            db,
            company_id,
            f"⚠️ I couldn't verify the provider balance ({exc.kind}): {exc} "
            "I'll keep the team paused and re-check shortly.",
        )
        return ResumeOutcome(still_exhausted=True)

    if not healthy:
        # The founder topped up the wrong account, or it hasn't propagated yet.
        await _post_ceo_dm(
            db,
            company_id,
            "⚠️ The provider account still reports an **insufficient balance**. "
            "Please double-check you topped up the right account; I'll re-check in "
            "~15 minutes.",
        )
        return ResumeOutcome(still_exhausted=True)

    # Balance confirmed: clear the ask and release the paused work.
    resumed = await _resume_paused_tasks(db, company_id)
    decision.status = DecisionStatus.approved
    await db.flush()
    await _post_ceo_dm(
        db,
        company_id,
        f"✅ Provider balance confirmed — resuming {len(resumed)} paused task(s). "
        "Back to work.",
    )
    return ResumeOutcome(resumed=True, resumed_task_ids=resumed)


async def dispatch_outcome(
    outcome: ResumeOutcome,
    *,
    company_id: uuid.UUID,
    enqueue_task,
    enqueue_recheck,
    recheck_delay_seconds: float,
) -> None:
    """Act on an :func:`attempt_resume` result over caller-supplied enqueuers.

    Enqueues each resumed task, and — when the balance is still empty — schedules
    the next re-check (the 15-minute resurface). Kept agnostic to *who* enqueues
    (the API or the worker both call this with their own arq helpers) so the two
    paths stay byte-for-byte consistent. Call after the session is committed.
    """
    for task_id in outcome.resumed_task_ids:
        await enqueue_task(task_id)
    if outcome.still_exhausted and enqueue_recheck is not None:
        await enqueue_recheck(company_id, delay_seconds=recheck_delay_seconds)
