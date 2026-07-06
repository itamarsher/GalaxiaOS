"""Server-Sent Events: a live snapshot stream of a company's tasks and budget.

Replaces frontend polling. The endpoint is auth'd via a ``?token=`` query param
(see :func:`app.deps.get_company_for_user_sse`) because the browser
``EventSource`` API cannot send an ``Authorization`` header.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.db import SessionLocal
from app.deps import CompanySseDep
from app.models import Budget, Task

router = APIRouter(prefix="/companies/{company_id}", tags=["events"])

# How often we re-query the DB for a fresh snapshot.
_POLL_SECONDS = 2.0
# Emit a heartbeat comment at least this often so proxies keep the stream open
# and the client can detect a dead connection even when nothing changes.
_HEARTBEAT_SECONDS = 15.0


async def _snapshot(company_id) -> dict:
    """Read the company's tasks + budget in a short-lived session."""
    async with SessionLocal() as db:
        tasks = (
            await db.scalars(
                select(Task)
                .where(Task.company_id == company_id)
                .order_by(Task.created_at.desc())
                .limit(200)
            )
        ).all()
        budget = await db.scalar(
            select(Budget).where(Budget.company_id == company_id).limit(1)
        )

    return {
        "tasks": [
            {
                "id": str(t.id),
                "agent_id": str(t.agent_id),
                "goal": t.goal,
                "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                "depth": t.depth,
                "cost_cents": t.cost_cents,
            }
            for t in tasks
        ],
        "budget": (
            {
                "spent_cents": budget.spent_cents,
                "reserved_cents": budget.reserved_cents,
                "limit_cents": budget.limit_cents,
            }
            if budget is not None
            else None
        ),
    }


@router.get("/events")
async def stream_events(company: CompanySseDep) -> StreamingResponse:
    """Stream company task/budget snapshots as Server-Sent Events.

    Emits a ``data:`` JSON frame only when the snapshot changes, plus a
    periodic heartbeat comment to keep the connection alive.
    """
    company_id = company.id

    async def gen():
        last_payload: str | None = None
        seconds_since_emit = 0.0
        # Prime the stream so the client renders immediately on connect.
        first = True
        while True:
            snapshot = await _snapshot(company_id)
            payload = json.dumps(snapshot, separators=(",", ":"), sort_keys=True)
            if first or payload != last_payload:
                last_payload = payload
                seconds_since_emit = 0.0
                first = False
                yield f"data: {payload}\n\n"
            else:
                seconds_since_emit += _POLL_SECONDS
                if seconds_since_emit >= _HEARTBEAT_SECONDS:
                    seconds_since_emit = 0.0
                    yield ": heartbeat\n\n"
            await asyncio.sleep(_POLL_SECONDS)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
