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
from app.models import Agent, DecisionRequest, FounderDigest, MemoryEntry, Task
from app.models.enums import AgentRole, AgentStatus, DecisionStatus
from app.providers.base import Message, ToolSpec
from app.runtime.cost_meter import CostMeter
from app.runtime.queue import enqueue_task
from app.services import apikeys, platform_requests
from app.services import budget as budget_svc
from app.services import memory as memory_svc
from app.services import runway as runway_svc

# Tools the founder-facing chat can actually act on: filing a capability request
# or a bug report routes to the Platform agent (it can't role-play "the product
# team" — there is no such team; this is the real mechanism).
_PLATFORM_REQUEST_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="request_capability",
        description="File a request for a new tool/capability the agents lack (routes to the Platform agent).",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "details": {"type": "string", "description": "What's needed and why."},
            },
            "required": ["title", "details"],
        },
    ),
    ToolSpec(
        name="report_bug",
        description="File a bug report about something broken (routes to the Platform agent).",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "details": {"type": "string"},
            },
            "required": ["title", "details"],
        },
    ),
]

_COMMAND_VERBS = (
    "pause", "resume", "stop", "halt", "increase", "decrease", "set", "raise", "lower",
    "request", "report", "file",
)

_ALLOWED_ACTIONS = {
    "pause_agents", "resume_agents", "pause_low_roi_agents", "set_budget",
    "request_capability", "report_bug", "none",
}

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


async def answer(db: AsyncSession, *, company_id: uuid.UUID, question: str) -> tuple[str, str]:
    """Return (answer_text, kind) where kind is 'query' or 'command'."""
    resolved = await apikeys.resolve_provider(db, company_id=company_id)
    if resolved is None:
        return ("Add a provider API key to use the copilot.", "query")
    provider, api_key = resolved

    if question.strip().lower().startswith(_COMMAND_VERBS):
        action = await _parse_command(provider, company_id, api_key, question)
        text = await _execute_command(db, company_id=company_id, action=action)
        return (text, "command")

    relevant = await memory_svc.query(db, company_id=company_id, text=question, limit=8)
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
            "You are the founder's copilot. Answer concisely and only from the company "
            "state provided. If the data does not support an answer, say so."
        ),
        messages=[Message(role="user", content=f"Company state:\n{state}\n\nQuestion: {question}")],
        max_tokens=600,
    )
    return (resp.text, "query")


async def _parse_command(provider, company_id: uuid.UUID, api_key: str, question: str) -> dict:
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


async def _execute_command(db: AsyncSession, *, company_id: uuid.UUID, action: dict) -> str:
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
        task_id = await platform_requests.file_request(
            db, company_id=company_id, kind=req_kind, title=title, details=details
        )
        if task_id is None:
            return (
                "I couldn't file that — this company has no Platform agent to handle it."
            )
        # Commit before enqueueing so the worker can't race ahead of the write.
        await db.commit()
        await enqueue_task(task_id)
        noun = "capability request" if req_kind == "capability" else "bug report"
        return (
            f"Filed a {noun} with the Platform agent: “{title}”. It will investigate the "
            "codebase and open a tracker issue."
        )

    return "I couldn't map that to a supported command. Try: pause/resume agents, or pause agents below an ROI threshold."


#: Cap replayed discussion turns so a long thread can't blow the context window.
_DECISION_CHAT_HISTORY_LIMIT = 20


async def discuss_decision(
    db: AsyncSession, *, company_id: uuid.UUID, decision, message: str, history=None
) -> str:
    """Answer a founder's question about a specific pending decision.

    Grounded in the decision itself (kind, summary, proposed action) plus current
    company state, so the founder can interrogate the trade-offs and reshape the
    call before approving/rejecting it. ``history`` is the prior turns of this
    discussion (oldest first); replaying them keeps the agent's answers coherent
    across a multi-turn back-and-forth instead of treating each reply in
    isolation.
    """
    resolved = await apikeys.resolve_provider(db, company_id=company_id)
    if resolved is None:
        return "Add a provider API key to discuss decisions with the agent."
    provider, api_key = resolved

    agent = await db.get(Agent, decision.agent_id) if decision.agent_id else None
    decision_ctx = (
        f"You raised this decision for the founder.\n"
        f"Agent: {agent.name if agent else 'unknown'} "
        f"({agent.role.value if agent else 'n/a'})\n"
        f"Kind: {decision.kind.value}\n"
        f"Summary: {decision.summary}\n"
        f"Proposed action / details: {json.dumps(decision.payload or {})}"
    )
    state = await _company_state(db, company_id)

    # A briefing turn (decision + live company state) anchors the thread, then the
    # prior turns are replayed verbatim, then the founder's new message. The
    # founder shows as the "user", the agent as the "assistant".
    messages: list[Message] = [
        Message(role="user", content=f"{decision_ctx}\n\nCompany state:\n{state}"),
        Message(role="assistant", content="Understood — ask me anything about this decision."),
    ]
    for turn in (history or [])[-_DECISION_CHAT_HISTORY_LIMIT:]:
        text = (turn.text or "").strip()
        if not text:
            continue
        role = "user" if turn.who == "you" else "assistant"
        messages.append(Message(role=role, content=text))
    messages.append(Message(role="user", content=message))

    meter = CostMeter(SessionLocal)
    resp = await meter.run_llm(
        provider,
        api_key=api_key,
        company_id=company_id,
        agent_id=None,
        task_id=None,
        model=provider.default_models["cheap"],
        system=(
            "You are the agent that raised this decision. Explain your reasoning, answer the "
            "founder's questions, and help them decide whether to approve, reject, or adjust it. "
            "Be concise, concrete, and honest about trade-offs and risks. If the founder asks for "
            "a change, describe exactly what you would do differently.\n"
            "If the founder asks you to request a new capability/tool or report a bug, actually do "
            "it by calling `request_capability` or `report_bug` — do NOT claim you'll route it to "
            "a team or person; those tools are the only real mechanism."
        ),
        messages=messages,
        tools=_PLATFORM_REQUEST_TOOLS,
        max_tokens=600,
    )

    # If the agent chose to file a capability/bug request, actually file it.
    filed = await _handle_platform_tool_calls(db, company_id=company_id, resp=resp)
    if filed:
        return (resp.text + "\n\n" if resp.text else "") + "\n".join(filed)
    return resp.text


async def _handle_platform_tool_calls(db, *, company_id: uuid.UUID, resp) -> list[str]:
    """Execute any request_capability/report_bug tool calls; return confirmations."""
    confirmations: list[str] = []
    enqueue_ids: list[uuid.UUID] = []
    for call in resp.tool_calls or []:
        if call.name not in ("request_capability", "report_bug"):
            continue
        req_kind = "capability" if call.name == "request_capability" else "bug"
        args = call.arguments if isinstance(call.arguments, dict) else {}
        title = str(args.get("title") or "").strip() or (
            "Capability request" if req_kind == "capability" else "Bug report"
        )
        details = str(args.get("details") or "").strip() or title
        task_id = await platform_requests.file_request(
            db, company_id=company_id, kind=req_kind, title=title, details=details
        )
        noun = "capability request" if req_kind == "capability" else "bug report"
        if task_id is None:
            confirmations.append(f"(Couldn't file the {noun} — no Platform agent exists.)")
        else:
            enqueue_ids.append(task_id)
            confirmations.append(
                f"✅ Filed a {noun} with the Platform agent: “{title}”. It will investigate and "
                "open a tracker issue."
            )
    if enqueue_ids:
        await db.commit()  # commit the new task(s) before enqueueing
        for task_id in enqueue_ids:
            await enqueue_task(task_id)
    return confirmations


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
    resolved = await apikeys.resolve_provider(db, company_id=company_id)
    summary = state
    if resolved is not None:
        provider, api_key = resolved
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
                "spend, risks, and any decisions needed. Markdown, <150 words."
            ),
            messages=[Message(role="user", content=state)],
            max_tokens=500,
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
