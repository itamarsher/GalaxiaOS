"""Founder-facing artifacts: create, list, and LLM-generate deliverables.

Agents file artifacts via the ``create_report`` tool; the founder can also ask for
one on demand. Generation is grounded in real company state + memory (same source
the copilot uses) and metered through the CostMeter like every other LLM call.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Artifact
from app.providers.base import Message
from app.runtime.cost_meter import CostMeter
from app.services import apikeys
from app.services import memory as memory_svc

#: Recognized report kinds with a one-line framing used to steer generation.
KINDS: dict[str, str] = {
    "investor_update": "a concise investor update a founder could forward to an investor",
    "growth_report": "a growth report covering acquisition, funnel, and what to do next",
    "research_report": "a market/competitive research report with a clear recommendation",
    "board_brief": "a board-level brief on progress, risks, and decisions needed",
    "custom": "a clear, well-structured report for the founder",
}


async def create_artifact(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    kind: str,
    title: str,
    body_md: str,
    source_task_id: uuid.UUID | None = None,
    source_agent_id: uuid.UUID | None = None,
    extra: dict | None = None,
) -> Artifact:
    artifact = Artifact(
        company_id=company_id,
        kind=(kind or "custom").strip()[:40] or "custom",
        title=(title or "Untitled report").strip()[:255],
        body_md=body_md or "",
        source_task_id=source_task_id,
        source_agent_id=source_agent_id,
        extra=extra,
    )
    db.add(artifact)
    await db.flush()
    return artifact


async def list_artifacts(db: AsyncSession, *, company_id: uuid.UUID, limit: int = 100) -> list[Artifact]:
    rows = await db.scalars(
        select(Artifact)
        .where(Artifact.company_id == company_id)
        .order_by(Artifact.created_at.desc())
        .limit(limit)
    )
    return list(rows)


async def get_artifact(
    db: AsyncSession, *, company_id: uuid.UUID, artifact_id: uuid.UUID
) -> Artifact | None:
    return await db.scalar(
        select(Artifact).where(Artifact.id == artifact_id, Artifact.company_id == company_id)
    )


async def generate_artifact(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    kind: str = "custom",
    instructions: str | None = None,
) -> Artifact | None:
    """Synthesize a report from real company state + memory and persist it.

    Returns ``None`` when no provider key is configured (the caller surfaces a
    helpful message). Imported lazily to avoid a circular import with copilot.
    """
    from app.services.copilot import _company_state

    resolved = await apikeys.resolve_provider(db, company_id=company_id)
    if resolved is None:
        return None
    provider, api_key = resolved

    framing = KINDS.get(kind, KINDS["custom"])
    relevant = await memory_svc.query(
        db, company_id=company_id, text=instructions or kind, limit=10
    )
    state = await _company_state(db, company_id, extra_memory=relevant)
    ask = instructions.strip() if instructions else f"Write {framing}."

    meter = CostMeter(SessionLocal)
    resp = await meter.run_llm(
        provider,
        api_key=api_key,
        company_id=company_id,
        agent_id=None,
        task_id=None,
        model=provider.default_models.get("planner", provider.default_models["cheap"]),
        system=(
            f"You write {framing} for a solo founder. Ground every claim ONLY in the "
            "company state provided — never invent metrics, traction, or events. Be honest "
            "about gaps. Output Markdown: a short title as an H1, then tight sections. "
            "If the data doesn't support a section, say so briefly rather than padding."
        ),
        messages=[Message(role="user", content=f"Company state:\n{state}\n\nTask: {ask}")],
        max_tokens=1200,
    )
    body = resp.text.strip()
    # Derive a title from the leading H1 when present, else fall back to the kind.
    title = kind.replace("_", " ").title()
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return await create_artifact(
        db,
        company_id=company_id,
        kind=kind,
        title=title,
        body_md=body,
        extra={"generated": True},
    )
