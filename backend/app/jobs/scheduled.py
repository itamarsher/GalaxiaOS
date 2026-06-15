"""arq cron entrypoints. Each iterates active companies in its own session."""

from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, set_tenant
from app.models import Company
from app.models.enums import CompanyStatus
from app.runtime import orchestrator
from app.services import copilot
from app.services import runway as runway_svc


async def _active_company_ids() -> list:
    async with SessionLocal() as db:
        rows = await db.scalars(
            select(Company.id).where(Company.status == CompanyStatus.active)
        )
        return list(rows)


async def recompute_runway(ctx: dict) -> dict:
    count = 0
    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            await runway_svc.recompute(db, company_id)
            await db.commit()
            count += 1
    return {"companies": count}


async def generate_digests(ctx: dict) -> dict:
    count = 0
    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            await copilot.generate_digest(db, company_id=company_id)
            await db.commit()
            count += 1
    return {"companies": count}


async def run_business_cycle(ctx: dict) -> dict:
    """Kick off a recurring business-cycle run for each active company."""
    if not settings.business_cycle_enabled:
        return {"skipped": True}

    from app.runtime.queue import enqueue_task

    count = 0
    enqueued = 0
    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            task_id = await orchestrator.create_scheduled_run(db, company_id)
            await db.commit()
        count += 1
        if task_id is not None:
            await enqueue_task(task_id)
            enqueued += 1
    return {"companies": count, "enqueued": enqueued}
