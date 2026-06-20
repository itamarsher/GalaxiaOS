"""Company Memory — write learnings and retrieve them by similarity + recency.

Writes compute an embedding via the :mod:`embeddings` seam. Recall pulls the most
similar entries (pgvector cosine distance over the HNSW index), then re-ranks them
by a recency-decayed similarity so stale memories sink — falling back to pure
recency when there's no query text or no usable embeddings.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
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
        embedding=await embeddings.embed_text(f"{title}\n{content}"),
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


def _recency_weight(created_at: datetime, now: datetime, half_life_days: float) -> float:
    """A multiplier in (0, 1] that halves every ``half_life_days`` of age."""
    if half_life_days <= 0:
        return 1.0
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / half_life_days)


def _rerank(
    scored: list[tuple[MemoryEntry, float]],
    *,
    now: datetime,
    half_life_days: float,
    limit: int,
) -> list[MemoryEntry]:
    """Re-rank ``(entry, cosine_distance)`` pairs by recency-decayed similarity.

    Similarity is ``1 - distance`` (higher = closer); it's scaled by the entry's
    recency weight so a fresh, relevant memory beats an old, equally-relevant one.
    """

    def score(pair: tuple[MemoryEntry, float]) -> float:
        entry, distance = pair
        return (1.0 - distance) * _recency_weight(entry.created_at, now, half_life_days)

    return [entry for entry, _ in sorted(scored, key=score, reverse=True)[:limit]]


async def query(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    text: str | None,
    limit: int = 8,
) -> list[MemoryEntry]:
    qvec = await embeddings.embed_text(text) if text else None

    if qvec is not None:
        # Pull a similarity-ranked candidate pool (uses the HNSW index), then
        # re-rank by recency-decayed similarity and keep the top ``limit``.
        pool = min(
            max(limit * settings.memory_candidate_multiplier, limit),
            settings.memory_candidate_cap,
        )
        distance = MemoryEntry.embedding.cosine_distance(qvec)
        stmt = (
            select(MemoryEntry, distance.label("distance"))
            .where(MemoryEntry.company_id == company_id, MemoryEntry.embedding.is_not(None))
            .order_by(distance)
            .limit(pool)
        )
        rows = (await db.execute(stmt)).all()
        if rows:
            scored = [(row[0], float(row[1])) for row in rows]
            return _rerank(
                scored,
                now=datetime.now(timezone.utc),
                half_life_days=settings.memory_recency_half_life_days,
                limit=limit,
            )

    # Fallback: most recent entries.
    rows = (
        await db.scalars(
            select(MemoryEntry)
            .where(MemoryEntry.company_id == company_id)
            .order_by(MemoryEntry.created_at.desc())
            .limit(limit)
        )
    ).all()
    return list(rows)


async def delete(db: AsyncSession, *, company_id: uuid.UUID, entry_id: uuid.UUID) -> bool:
    """Forget one memory entry (founder-curated). Tenant-scoped; ``False`` if absent."""
    entry = await db.scalar(
        select(MemoryEntry).where(MemoryEntry.id == entry_id, MemoryEntry.company_id == company_id)
    )
    if entry is None:
        return False
    await db.delete(entry)
    await db.flush()
    return True
