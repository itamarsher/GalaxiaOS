"""arq cron entrypoints. Each iterates active companies in its own session."""

from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, set_tenant
from app.models import Company
from app.models.enums import CompanyStatus
from app.runtime import orchestrator
from app.services import copilot, provider_balance
from app.services import memory as memory_svc
from app.services import runway as runway_svc
from app.services import sites as sites_svc


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


async def reconcile_site_domains(ctx: dict) -> dict:
    """Advance in-flight domain connections toward ``live``.

    DNS zone activation and TLS issuance take minutes (and happen out-of-band after
    a founder delegates nameservers), so a connection can't finish inside the agent
    task that started it. This periodically pushes each non-terminal ``SiteDomain``
    one step further (zone active -> attach domain -> HTTPS live).
    """
    advanced = 0
    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            for sd in await sites_svc.pending_connections(db, company_id=company_id):
                await sites_svc.advance_connection(db, sd=sd)
                advanced += 1
            await db.commit()
    return {"advanced": advanced}


async def backfill_memory_embeddings(ctx: dict) -> dict:
    """Re-embed memories left without a vector (e.g. written while a remote
    embedder was cold). Probes the embedder per company and skips quietly when it
    isn't ready yet, so a cold/down embedding service costs nothing but a retry."""
    if not settings.embedding_backfill_enabled:
        return {"skipped": True}
    scanned = updated = 0
    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            res = await memory_svc.backfill_embeddings(
                db, company_id=company_id, limit=settings.embedding_backfill_batch
            )
            await db.commit()
        scanned += res["scanned"]
        updated += res["updated"]
    return {"scanned": scanned, "updated": updated}


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
            # Skip companies that are already busy — continuous mode keeps a run
            # going, so the daily cron is only a fallback for idle orgs and must
            # not stack a second, parallel run on top of a live one. Also skip a
            # company whose provider account is dry (its tasks are paused awaiting
            # a founder top-up); a new run would only hit the same refusal.
            if await orchestrator.has_active_tasks(
                db, company_id
            ) or await provider_balance.is_exhausted(db, company_id):
                count += 1
                continue
            task_id = await orchestrator.create_scheduled_run(db, company_id)
            await db.commit()
        count += 1
        if task_id is not None:
            await enqueue_task(task_id)
            enqueued += 1
    return {"companies": count, "enqueued": enqueued}
