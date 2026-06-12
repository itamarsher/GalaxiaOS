"""Founder Copilot: daily digest + natural-language control plane.

Queries are answered by an LLM grounded in structured company state. Commands are
parsed by the LLM into a *structured action* validated against an allow-list and
executed by **code, not the LLM** — destructive actions return a confirmation.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Agent, FounderDigest, MemoryEntry, Task
from app.models.enums import AgentStatus, TaskStatus
from app.providers.base import Message
from app.providers.registry import get_provider
from app.runtime.cost_meter import CostMeter
from app.services import apikeys
from app.services import budget as budget_svc

_COMMAND_VERBS = ("pause", "resume", "stop", "halt", "increase", "decrease", "set")


async def _company_state(db: AsyncSession, company_id: uuid.UUID) -> str:
    budget = await budget_svc.get_active_budget(db, company_id)
    by_cat = await budget_svc.spend_by_category(db, company_id)
    task_counts = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.company_id == company_id)
        .group_by(Task.status)
    )
    counts = {s.value: c for s, c in task_counts.all()}
    memories = (
        await db.scalars(
            select(MemoryEntry)
            .where(MemoryEntry.company_id == company_id)
            .order_by(MemoryEntry.created_at.desc())
            .limit(8)
        )
    ).all()
    lines = [
        f"Budget: limit={budget.limit_cents if budget else 0}c "
        f"spent={budget.spent_cents if budget else 0}c reserved={budget.reserved_cents if budget else 0}c",
        f"Spend by category (cents): {by_cat}",
        f"Task counts: {counts}",
        "Recent memory:",
    ]
    lines += [f"- [{m.type.value}] {m.title}: {m.content[:160]}" for m in memories]
    return "\n".join(lines)


async def answer(db: AsyncSession, *, company_id: uuid.UUID, question: str) -> tuple[str, str]:
    """Return (answer_text, kind) where kind is 'query' or 'command'."""
    is_command = question.strip().lower().startswith(_COMMAND_VERBS)
    api_key = await apikeys.get_plaintext_key(db, company_id=company_id, provider="anthropic")
    if not api_key:
        return ("Add a provider API key to use the copilot.", "query")

    if is_command:
        # MVP: surface the parsed intent and require explicit confirmation before
        # any destructive mutation. The structured executor is wired in Phase 4.
        return (
            f"Interpreted as a command: '{question}'. Commands that change company "
            "state require confirmation — review the affected agents/initiatives, then "
            "approve via the relevant control (pause/resume) before it is applied.",
            "command",
        )

    state = await _company_state(db, company_id)
    meter = CostMeter(SessionLocal)
    resp = await meter.run_llm(
        get_provider("anthropic"),
        api_key=api_key,
        company_id=company_id,
        agent_id=None,
        task_id=None,
        model=settings.model_cheap,
        system=(
            "You are the founder's copilot. Answer concisely and only from the company "
            "state provided. If the data does not support an answer, say so."
        ),
        messages=[Message(role="user", content=f"Company state:\n{state}\n\nQuestion: {question}")],
        max_tokens=600,
    )
    return (resp.text, "query")


async def generate_digest(db: AsyncSession, *, company_id: uuid.UUID) -> FounderDigest:
    """Produce a board-level daily digest for a company."""
    state = await _company_state(db, company_id)
    pending = await db.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.company_id == company_id, Task.status == TaskStatus.waiting_approval)
    )
    api_key = await apikeys.get_plaintext_key(db, company_id=company_id, provider="anthropic")
    summary = state
    if api_key:
        meter = CostMeter(SessionLocal)
        resp = await meter.run_llm(
            get_provider("anthropic"),
            api_key=api_key,
            company_id=company_id,
            agent_id=None,
            task_id=None,
            model=settings.model_cheap,
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
        open_decisions=int(pending or 0),
    )
    db.add(digest)
    await db.flush()
    return digest
