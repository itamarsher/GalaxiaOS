"""Company Memory — write learnings and retrieve them by similarity + recency.

Writes compute an embedding via the :mod:`embeddings` seam. Recall pulls the most
similar entries (pgvector cosine distance over the HNSW index), then re-ranks them
by a recency-decayed similarity so stale memories sink — falling back to pure
recency when there's no query text or no usable embeddings.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
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
    labels: list[str] | None = None,
) -> MemoryEntry:
    entry = MemoryEntry(
        company_id=company_id,
        type=type,
        title=title[:500],
        content=content,
        structured=structured,
        source_task_id=source_task_id,
        # Data-segmentation labels: sensitive sources (financial, legal, filed docs)
        # pass their labels so recall can withhold them; general memory stays NULL.
        labels=labels or None,
        embedding=await embeddings.embed_text(f"{title}\n{content}"),
    )
    db.add(entry)
    await db.flush()
    return entry


async def backfill_embeddings(
    db: AsyncSession, *, company_id: uuid.UUID, limit: int = 50
) -> dict:
    """Re-embed entries written with no vector (``embedding IS NULL``).

    A memory write embeds inline, so a row ends up null only when the embedder was
    unavailable at write time — most often a ``remote`` embedding service still
    cold-starting (it returns no vector rather than a non-semantic one). This heals
    those rows on a later pass once the embedder is warm, so recall isn't
    permanently blind to them.

    Bounded and self-throttling for the small free-tier box:

    - Loads at most ``limit`` rows, and only the columns needed to embed (id +
      title + content), never the heavy ``structured``/``embedding`` columns.
    - Probes the embedder once first; if it's still unavailable (None), it skips
      the whole pass rather than churning the backlog against a cold/down service
      — the next run retries. (The probe doubles as a keep-warm ping.)
    - Writes each vector with a narrow ``UPDATE … WHERE id`` so no ORM row is held.
    """
    # Probe: if the embedder can't produce a vector right now, don't burn the
    # backlog — every row this pass would miss too. Retry next cycle.
    if await embeddings.embed_text("ok") is None:
        return {"scanned": 0, "updated": 0, "embedder_ready": False}

    rows = (
        await db.execute(
            select(MemoryEntry.id, MemoryEntry.title, MemoryEntry.content)
            .where(MemoryEntry.company_id == company_id, MemoryEntry.embedding.is_(None))
            .order_by(MemoryEntry.created_at.desc())
            .limit(limit)
        )
    ).all()

    updated = 0
    for entry_id, title, content in rows:
        vec = await embeddings.embed_text(f"{title}\n{content}")
        if vec is None:
            # Rare once the probe passed (e.g. a transient miss); skip this row and
            # let a later pass pick it up, rather than stalling the whole batch.
            continue
        await db.execute(
            update(MemoryEntry).where(MemoryEntry.id == entry_id).values(embedding=vec)
        )
        updated += 1
    return {"scanned": len(rows), "updated": updated, "embedder_ready": True}


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
