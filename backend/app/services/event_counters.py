"""Per-company event counters — increment at chokepoints, read for the dashboard.

The runtime calls :func:`record` at its natural chokepoints (an LLM completion, a
tool call, a task lifecycle transition, a decision escalation, an outbound
message, an escalated error). Each call upserts one row in ``event_counters``,
bumping ``count`` and ``last_event_at`` for that ``(company_id, event_type)``.

Two properties matter:

* **Atomic** — the increment is a single ``INSERT … ON CONFLICT DO UPDATE`` so
  concurrent workers never lose a tick.
* **Non-fatal** — :func:`record` runs inside a SAVEPOINT and swallows errors, so a
  counter hiccup can never poison or fail the business transaction it rides on.
  Counting is telemetry; it must never take down the work being counted.

Callers that already hold a tenant-scoped session pass it to :func:`record` (the
increment joins their transaction and commits with it). Callers without one use
:func:`record_standalone`, which opens its own short session.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

from app.db import SessionLocal, set_tenant
from app.models.enums import EventType
from app.models.event_counter import EventCounter
from app.observability import get_logger

_log = get_logger("abos.events")


async def record(
    db: AsyncSession, *, company_id: uuid.UUID, event_type: EventType | str, n: int = 1
) -> None:
    """Increment a company's counter for ``event_type`` by ``n`` (best-effort).

    Joins the caller's transaction; isolated in a SAVEPOINT so a failure rolls
    back only the counter, never the surrounding work. Assumes the session is
    already tenant-scoped (``set_tenant``), as every runtime chokepoint is.
    """
    if n <= 0:
        return
    value = event_type.value if isinstance(event_type, EventType) else str(event_type)
    stmt = (
        pg_insert(EventCounter)
        .values(company_id=company_id, event_type=value, count=n, last_event_at=func.now())
        .on_conflict_do_update(
            constraint="uq_event_counters_company_type",
            set_={
                "count": EventCounter.count + n,
                "last_event_at": func.now(),
                "updated_at": func.now(),
            },
        )
    )
    try:
        async with db.begin_nested():
            await db.execute(stmt)
    except Exception:  # noqa: BLE001 — counting must never break the work it counts
        _log.exception("event_counter_increment_failed", extra={"extra_fields": {"event": value}})


async def record_standalone(
    *,
    company_id: uuid.UUID,
    event_type: EventType | str,
    n: int = 1,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Increment a counter from a caller that holds no session of its own.

    Opens a short tenant-scoped session, increments, and commits. Best-effort:
    any failure is logged and swallowed.
    """
    sf = session_factory or SessionLocal
    try:
        async with sf() as db:
            await set_tenant(db, company_id)
            await record(db, company_id=company_id, event_type=event_type, n=n)
            await db.commit()
    except Exception:  # noqa: BLE001
        _log.exception("event_counter_standalone_failed")


async def totals(db: AsyncSession, *, company_id: uuid.UUID) -> dict[str, int]:
    """Return ``{event_type: count}`` for a company (missing types omitted)."""
    rows = await db.execute(
        select(EventCounter.event_type, EventCounter.count).where(
            EventCounter.company_id == company_id
        )
    )
    return {event_type: int(count) for event_type, count in rows.all()}


async def snapshot(db: AsyncSession, *, company_id: uuid.UUID) -> list[dict]:
    """Return every counter row for a company (type, count, last_event_at), sorted."""
    rows = (
        await db.scalars(
            select(EventCounter)
            .where(EventCounter.company_id == company_id)
            .order_by(EventCounter.count.desc())
        )
    ).all()
    return [
        {
            "event_type": r.event_type,
            "count": int(r.count),
            "last_event_at": r.last_event_at.isoformat() if r.last_event_at else None,
        }
        for r in rows
    ]
