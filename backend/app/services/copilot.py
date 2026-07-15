"""Founder Copilot: daily digest + natural-language control plane.

Queries are answered by an LLM grounded in structured company state plus
semantically-retrieved memory. Commands are parsed by the LLM into a *structured
action* validated against an allow-list and executed by **code, not the LLM**;
reversible actions (pause/resume) run immediately, destructive ones (budget
changes) return a confirmation instead of mutating.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Agent, DecisionRequest, FounderDigest, MemoryEntry, Mission, Task
from app.models.enums import AgentRole, AgentStatus, DecisionStatus
from app.providers.base import Message
from app.runtime.cost_meter import CostMeter
from app.runtime.prompts import operating_language_directive
from app.services import apikeys, platform_requests
from app.services import budget as budget_svc
from app.services import memory as memory_svc
from app.services import runway as runway_svc

_COMMAND_VERBS = (
    "pause", "resume", "stop", "halt", "increase", "decrease", "set", "raise", "lower",
    "request", "report", "file",
)

_ALLOWED_ACTIONS = {
    "pause_agents", "resume_agents", "pause_low_roi_agents", "set_budget",
    "request_capability", "report_bug", "none",
}

# The copilot is an INTERACTIVE chat with the founder, so — unlike the agent loop
# and the one-way digest, which are pinned to the persisted mission.language for
# deterministic deliverables — it must reply in whatever language the founder is
# writing in right now. A founder who onboarded in one language (mission.language)
# but asks in another was getting answers that flip-flopped: a full sentence
# anchored their language, but a terse "yes"/"ok" let the mission-language
# directive (and the possibly-other-language company state/memory in the prompt)
# take over and switch the reply. Mirror the conversation instead.
COPILOT_REPLY_LANGUAGE_DIRECTIVE = (
    "Language: reply in the SAME language the founder is writing in. Mirror the "
    "language of their latest message; when it is too short to tell (e.g. \"yes\", "
    "\"ok\", \"go ahead\"), match the language of the earlier conversation. The "
    "company state and memory below are internal data and may be in a different "
    "language — do NOT let their language change the language you reply in. Never "
    "switch languages on your own."
)

COMMAND_PARSE_SYSTEM = """Translate the founder's command into ONE structured action.
Respond ONLY with minified JSON:
{"action": "pause_agents|resume_agents|pause_low_roi_agents|set_budget|request_capability|report_bug|none",
 "roles": ["growth","research","product","finance","governance","ceo"],
 "all": false, "roi_lt": 0.05, "value_cents": 50000,
 "title": "short title", "details": "what's needed and why"}
Rules: include only the fields relevant to the action. Use "pause_low_roi_agents" for
commands about pausing by ROI/performance threshold (set roi_lt). Use "all": true to target
every agent. Use "request_capability" when the founder wants a new tool/capability the agents
lack (e.g. real web search), and "report_bug" when they want something broken reported — fill
title and details for both. Use "none" if the command cannot be mapped to one of these actions."""


async def _company_language(db: AsyncSession, company_id: uuid.UUID) -> str | None:
    """The founder's language (BCP-47), detected once at onboarding. Copilot answers
    and digests use it so this founder-facing surface stays in the founder's language
    deterministically, same as the agent loop — not just whatever the model defaults to."""
    return await db.scalar(select(Mission.language).where(Mission.company_id == company_id))


async def _company_state(db: AsyncSession, company_id: uuid.UUID, extra_memory=None) -> str:
    budget = await budget_svc.get_active_budget(db, company_id)
    by_cat = await budget_svc.spend_by_category(db, company_id)
    task_counts = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.company_id == company_id)
        .group_by(Task.status)
    )
    counts = {s.value: c for s, c in task_counts.all()}
    memories = extra_memory if extra_memory is not None else await memory_svc.query(
        db, company_id=company_id, text=None, limit=8
    )
    lines = [
        f"Budget: limit={budget.limit_cents if budget else 0}c "
        f"spent={budget.spent_cents if budget else 0}c reserved={budget.reserved_cents if budget else 0}c",
        f"Spend by category (cents): {by_cat}",
        f"Task counts: {counts}",
        "Relevant memory:",
    ]
    lines += [f"- [{m.type.value}] {m.title}: {m.content[:160]}" for m in memories]
    return "\n".join(lines)


# How many prior turns of the conversation to carry into a query. Bounds the
# token cost of grounding a follow-up while keeping enough context that a terse
# reply ("sounds good", "do it") still resolves against what was just discussed.
_HISTORY_TURNS = 10
# Cap each carried turn so a single long answer can't blow the context budget.
_HISTORY_CHAR_CAP = 1200


def _recent_history(history) -> list[Message]:
    """Sanitize caller-supplied prior turns into provider ``Message``s.

    Keeps only the last :data:`_HISTORY_TURNS`, coerces the role to the two the
    providers accept, drops empties, and truncates each turn. History is the
    fix for the copilot answering follow-ups (e.g. "sounds good") out of
    context: without it, each ask is stateless and the model confabulates.
    """
    messages: list[Message] = []
    for turn in (history or [])[-_HISTORY_TURNS:]:
        if isinstance(turn, Message):
            role, content = turn.role, turn.content
        else:
            role, content = turn.get("role"), turn.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        role = "assistant" if role == "assistant" else "user"
        messages.append(Message(role=role, content=content.strip()[:_HISTORY_CHAR_CAP]))
    return messages


def _retrieval_text(history_messages: list[Message], question: str) -> str:
    """Query text for memory retrieval that survives terse follow-ups.

    A bare "sounds good" retrieves nothing useful on its own, so fold in the
    most recent user turn to inherit the topic ("buy the domain", "referral
    program") the founder is actually responding to.
    """
    prior_user = next(
        (m.content for m in reversed(history_messages) if m.role == "user"), ""
    )
    return f"{prior_user}\n{question}".strip() if prior_user else question


async def answer(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    question: str,
    user_id: uuid.UUID | None = None,
    history=None,
) -> tuple[str, str]:
    """Return (answer_text, kind) where kind is 'query' or 'command'.

    ``user_id`` is the founder asking; it is attributed to any capability/bug
    request this command files, so the backlog tracks who asked.

    ``history`` is the prior conversation (a list of ``{"role","content"}`` dicts
    or :class:`Message`), oldest first, excluding the current ``question``. It
    grounds conversational follow-ups on the query path so the copilot answers
    in context instead of confabulating from an unrelated memory hit.
    """
    resolved = await apikeys.resolve_active_provider(db, company_id=company_id)
    if resolved is None:
        return (
            "No model available for the copilot — add your own provider key, or (managed mode) "
            "the free platform allowance is used up; upgrade or bring a key.",
            "query",
        )
    provider, api_key = resolved.provider, resolved.api_key
    funding_user_id = resolved.funding_user_id

    if question.strip().lower().startswith(_COMMAND_VERBS):
        action = await _parse_command(
            provider, company_id, api_key, question, funding_user_id=funding_user_id
        )
        text = await _execute_command(
            db, company_id=company_id, action=action, user_id=user_id
        )
        return (text, "command")

    prior = _recent_history(history)
    relevant = await memory_svc.query(
        db, company_id=company_id, text=_retrieval_text(prior, question), limit=8
    )
    state = await _company_state(db, company_id, extra_memory=relevant)
    meter = CostMeter(SessionLocal)
    resp = await meter.run_llm(
        provider,
        api_key=api_key,
        company_id=company_id,
        agent_id=None,
        task_id=None,
        model=provider.default_models["cheap"],
        system=(
            "You are the founder's copilot in an ongoing conversation. Answer concisely, "
            "grounded in the company state provided and the conversation so far — a short "
            "reply like \"sounds good\" refers to what was just discussed, not a new topic. "
            "If the data does not support an answer, say so rather than inventing one.\n\n"
            + COPILOT_REPLY_LANGUAGE_DIRECTIVE
        ),
        messages=[
            *prior,
            Message(role="user", content=f"Company state:\n{state}\n\nQuestion: {question}"),
        ],
        max_tokens=600,
        funding_user_id=funding_user_id,
    )
    return (resp.text, "query")


async def _parse_command(
    provider, company_id: uuid.UUID, api_key: str, question: str, *, funding_user_id=None
) -> dict:
    meter = CostMeter(SessionLocal)
    resp = await meter.run_llm(
        provider,
        api_key=api_key,
        company_id=company_id,
        agent_id=None,
        task_id=None,
        model=provider.default_models["cheap"],
        system=COMMAND_PARSE_SYSTEM,
        messages=[Message(role="user", content=question)],
        max_tokens=200,
        funding_user_id=funding_user_id,
    )
    try:
        text = resp.text
        action = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {"action": "none"}
    if action.get("action") not in _ALLOWED_ACTIONS:
        return {"action": "none"}
    return action


async def _resolve_agents(db, company_id: uuid.UUID, action: dict) -> list[Agent]:
    stmt = select(Agent).where(Agent.company_id == company_id)
    roles = action.get("roles")
    if roles and not action.get("all"):
        try:
            stmt = stmt.where(Agent.role.in_([AgentRole(r) for r in roles]))
        except ValueError:
            return []
    return list((await db.scalars(stmt)).all())


async def _execute_command(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    action: dict,
    user_id: uuid.UUID | None = None,
) -> str:
    kind = action.get("action")

    if kind == "pause_low_roi_agents":
        threshold = float(action.get("roi_lt", settings.roi_pause_floor))
        paused = await runway_svc.pause_low_roi_agents(db, company_id, threshold)
        return f"Paused {len(paused)} agent(s) with ROI below {threshold:.0%}."

    if kind in ("pause_agents", "resume_agents"):
        new_status = AgentStatus.paused if kind == "pause_agents" else AgentStatus.active
        agents = await _resolve_agents(db, company_id, action)
        changed = [a for a in agents if a.status is not new_status]
        for a in changed:
            a.status = new_status
        await db.flush()
        verb = "Paused" if new_status is AgentStatus.paused else "Resumed"
        names = ", ".join(a.name for a in changed) or "no matching agents"
        return f"{verb} {len(changed)} agent(s): {names}."

    if kind == "set_budget":
        value = action.get("value_cents")
        return (
            f"This would change the monthly budget to ${(value or 0) / 100:.2f}. Budget changes "
            "are not applied automatically — confirm via the budget control (PATCH /budget) to proceed."
        )

    if kind in ("request_capability", "report_bug"):
        req_kind = "capability" if kind == "request_capability" else "bug"
        title = str(action.get("title") or "").strip() or (
            "Capability request" if req_kind == "capability" else "Bug report"
        )
        details = str(action.get("details") or "").strip() or title
        outcome = await platform_requests.file_request(
            db, company_id=company_id, kind=req_kind, title=title, details=details,
            user_id=user_id,
        )
        if outcome is None:
            return "I couldn't file that — I couldn't tell if it was a bug or a capability request."
        return _confirm_request(req_kind, outcome)

    return "I couldn't map that to a supported command. Try: pause/resume agents, or pause agents below an ROI threshold."


def _confirm_request(req_kind: str, outcome) -> str:
    """Founder-facing confirmation that a request was logged to the backlog."""
    noun = "capability request" if req_kind == "capability" else "bug report"
    if outcome.is_new_feature:
        return (
            f"Logged a {noun} in the feature-request backlog: “{outcome.title}” "
            f"(demand: {outcome.votes}). The abos team's promoter reviews the backlog "
            "and files it as a tracker issue when there's enough demand."
        )
    if outcome.is_new_vote:
        return (
            f"That {noun} already exists — added your vote for “{outcome.title}” "
            f"(demand now {outcome.votes})."
        )
    return (
        f"You'd already requested “{outcome.title}”; it stays at {outcome.votes} "
        "vote(s). I refreshed the details."
    )


async def _pending_decisions(db: AsyncSession, company_id: uuid.UUID) -> int:
    """Count items actually sitting in the founder's decision inbox.

    The digest's ``open_decisions`` must match what the Decisions tab shows, so
    it counts pending :class:`DecisionRequest` rows — *not* waiting-approval
    tasks, which can drift out of sync with the inbox.
    """
    count = await db.scalar(
        select(func.count())
        .select_from(DecisionRequest)
        .where(
            DecisionRequest.company_id == company_id,
            DecisionRequest.status == DecisionStatus.pending,
        )
    )
    return int(count or 0)


async def _state_fingerprint(db: AsyncSession, company_id: uuid.UUID) -> str:
    """A cheap hash of the company state that a digest summarizes.

    Used to decide whether the cached digest is still current: if nothing that a
    digest would mention has changed (spend, task mix, pending decisions, newest
    task/memory timestamps), the fingerprint is identical and we skip the LLM.
    """
    budget = await budget_svc.get_active_budget(db, company_id)
    task_counts = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.company_id == company_id)
        .group_by(Task.status)
    )
    counts = {s.value: c for s, c in task_counts.all()}
    last_task = await db.scalar(
        select(func.max(Task.updated_at)).where(Task.company_id == company_id)
    )
    last_memory = await db.scalar(
        select(func.max(MemoryEntry.created_at)).where(MemoryEntry.company_id == company_id)
    )
    raw = json.dumps(
        {
            "spent": budget.spent_cents if budget else 0,
            "reserved": budget.reserved_cents if budget else 0,
            "limit": budget.limit_cents if budget else 0,
            "tasks": counts,
            "pending_decisions": await _pending_decisions(db, company_id),
            "last_task": last_task.isoformat() if last_task else None,
            "last_memory": last_memory.isoformat() if last_memory else None,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


async def generate_digest(
    db: AsyncSession, *, company_id: uuid.UUID, state_hash: str | None = None
) -> FounderDigest:
    """Produce a board-level daily digest for a company."""
    state = await _company_state(db, company_id)
    if state_hash is None:
        state_hash = await _state_fingerprint(db, company_id)
    pending = await _pending_decisions(db, company_id)
    resolved = await apikeys.resolve_active_provider(db, company_id=company_id)
    summary = state
    if resolved is not None:
        provider, api_key = resolved.provider, resolved.api_key
        language = await _company_language(db, company_id)
        meter = CostMeter(SessionLocal)
        resp = await meter.run_llm(
            provider,
            api_key=api_key,
            company_id=company_id,
            agent_id=None,
            task_id=None,
            model=provider.default_models["cheap"],
            system=(
                "Write a terse board update for a solo founder: yesterday's progress, "
                "spend, risks, and any decisions needed. Markdown, <150 words.\n\n"
                + operating_language_directive(language)
            ),
            messages=[Message(role="user", content=state)],
            max_tokens=500,
            funding_user_id=resolved.funding_user_id,
        )
        summary = resp.text

    digest = FounderDigest(
        company_id=company_id,
        period_date=date.today(),
        summary_md=summary,
        open_decisions=pending,
        metrics={"state_hash": state_hash},
    )
    db.add(digest)
    await db.flush()
    return digest


async def get_or_refresh_digest(
    db: AsyncSession, *, company_id: uuid.UUID
) -> FounderDigest:
    """Return the latest digest, regenerating only when state has changed.

    Called when the Overview tab loads: the first visit auto-creates a digest,
    subsequent visits return the cached one for free, and a new digest is
    produced only once there is genuinely new information to summarize.
    """
    fingerprint = await _state_fingerprint(db, company_id)
    latest = await db.scalar(
        select(FounderDigest)
        .where(FounderDigest.company_id == company_id)
        .order_by(FounderDigest.period_date.desc(), FounderDigest.created_at.desc())
        .limit(1)
    )
    if latest is not None and (latest.metrics or {}).get("state_hash") == fingerprint:
        return latest
    return await generate_digest(db, company_id=company_id, state_hash=fingerprint)
