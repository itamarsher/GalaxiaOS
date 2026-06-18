"""Company Memory — write learnings and retrieve them by semantic similarity.

Writes compute an embedding via the :mod:`embeddings` seam; queries use pgvector
cosine distance, falling back to recency when a query/embeddings are unavailable.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MemoryEntry
from app.models.enums import MemoryType
from app.services import embeddings


async def write(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    type: MemoryType,
    title: str,
    content: str,
    source_task_id: uuid.UUID | None = None,
    structured: dict | None = None,
) -> MemoryEntry:
    entry = MemoryEntry(
        company_id=company_id,
        type=type,
        title=title[:500],
        content=content,
        structured=structured,
        source_task_id=source_task_id,
        embedding=embeddings.embed(f"{title}\n{content}"),
    )
    db.add(entry)
    await db.flush()
    return entry


async def find_latest_by_title(
    db: AsyncSession, *, company_id: uuid.UUID, title: str
) -> MemoryEntry | None:
    """Return the most recent entry with this exact title for the company, or ``None``.

    Used to deduplicate append-only records (e.g. internally-tracked platform
    requests) so repeated reports update a single counted entry instead of stacking
    duplicates.
    """
    stmt = (
        select(MemoryEntry)
        .where(MemoryEntry.company_id == company_id, MemoryEntry.title == title[:500])
        .order_by(MemoryEntry.created_at.desc())
        .limit(1)
    )
    return await db.scalar(stmt)


async def query(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    text: str | None,
    limit: int = 8,
) -> list[MemoryEntry]:
    base = select(MemoryEntry).where(MemoryEntry.company_id == company_id)
    qvec = embeddings.embed(text) if text else None

    if qvec is not None:
        stmt = (
            base.where(MemoryEntry.embedding.is_not(None))
            .order_by(MemoryEntry.embedding.cosine_distance(qvec))
            .limit(limit)
        )
        rows = (await db.scalars(stmt)).all()
        if rows:
            return list(rows)

    # Fallback: most recent entries.
    rows = (
        await db.scalars(base.order_by(MemoryEntry.created_at.desc()).limit(limit))
    ).all()
    return list(rows)
