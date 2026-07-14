"""arq cron entrypoints. Each iterates active companies in its own session."""

from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, set_tenant
from app.models import Company
from app.models.enums import CompanyStatus
from app.runtime import orchestrator
from app.services import copilot
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


async def promote_feature_backlog(ctx: dict) -> dict:
    """Drain the shared feature-request backlog into tracker issues on the platform
    company's behalf.

    Runs UNSCOPED (no ``set_tenant``): the backlog is a cross-company ledger, so the
    promoter must see every company's votes. Skips until a platform company has been
    designated (the first onboarded company) or when no tracker is connected.
    """
    if not settings.platform_promote_enabled:
        return {"skipped": True}
    from app.services import platform_company, promoter

    async with SessionLocal() as db:
        company_id = await platform_company.platform_company_id(db)
        if company_id is None:
            return {"skipped": "no_platform_company"}
        result = await promoter.promote_backlog(
            db,
            company_id=company_id,
            min_votes=settings.platform_promote_min_votes,
            limit=settings.platform_promote_batch,
        )
        await db.commit()
    return result


async def reconcile_delivered_requests(ctx: dict) -> dict:
    """Flip promoted backlog entries to ``delivered`` once their issue closes.

    Closes the dogfooding loop: when a promoted request's tracker issue is closed
    (its fix merged), mark it delivered and notify the requesting companies. Runs
    unscoped for the same cross-company reason as the promoter.
    """
    if not settings.platform_reconcile_enabled:
        return {"skipped": True}
    from app.services import platform_company, promoter

    async with SessionLocal() as db:
        company_id = await platform_company.platform_company_id(db)
        if company_id is None:
            return {"skipped": "no_platform_company"}
        result = await promoter.reconcile_delivered(
            db, company_id=company_id, limit=settings.platform_reconcile_batch
        )
        await db.commit()
    return result


async def triage_founder_decisions(ctx: dict) -> dict:
    """Notify the founder's webhook of pending decisions, and auto-resolve the
    routine ones when the Claude delegate is enabled (see app.services.delegate).

    Runs per active company that has a delegate configured; a company with no
    config is skipped untouched. Heavy work (the LLM triage, the webhook POST) is
    kept off the agent hot path — this cron is its own place. Auto-resolutions go
    through the normal decision-resolution path, so their resumed tasks are
    enqueued exactly like a founder's click.
    """
    if not settings.delegate_enabled:
        return {"skipped": True}
    from app.runtime.queue import enqueue_task
    from app.services import delegate

    to_enqueue: list = []
    webhooks: list[tuple[str, dict]] = []
    handled = 0

    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            cfg = await delegate.get_config(db, company_id)
            if cfg is None or not cfg.active:
                continue
            company = await db.get(Company, company_id)
            if company is None:
                continue
            for decision in await delegate.untriaged_pending(db, company_id):
                outcome = await delegate.handle(db, company=company, decision=decision, cfg=cfg)
                handled += 1
                if outcome.resumed_task_id is not None:
                    to_enqueue.append(outcome.resumed_task_id)
                if outcome.webhook_payload is not None and cfg.webhook_url:
                    webhooks.append((cfg.webhook_url, outcome.webhook_payload))
            await db.commit()

    # Fire side effects only after the DB is durably committed.
    from app.services import delegate as _delegate

    for task_id in to_enqueue:
        await enqueue_task(task_id)
    for url, payload in webhooks:
        await _delegate.send_webhook(url, payload)
    return {"handled": handled, "resumed": len(to_enqueue), "notified": len(webhooks)}


async def monitor_failed_tasks(ctx: dict) -> dict:
    """The platform company watches its own failed tasks and wakes the Platform
    agent to investigate + report bugs (feeding the Claude Code auto-fix pipeline).

    Skips until a platform company is designated. Enqueues the investigation tasks
    it creates so the Platform agent actually runs them.
    """
    if not settings.platform_failure_monitor_enabled:
        return {"skipped": True}
    from app.runtime.queue import enqueue_task
    from app.services import platform_company, reliability

    async with SessionLocal() as db:
        company_id = await platform_company.platform_company_id(db)
        if company_id is None:
            return {"skipped": "no_platform_company"}
        result = await reliability.review_failed_tasks(
            db, company_id=company_id, limit=settings.platform_failure_monitor_batch
        )
        await db.commit()
    for task_id in result["review_task_ids"]:
        await enqueue_task(task_id)
    return {"reviewed": result["reviewed"], "enqueued": len(result["review_task_ids"])}


async def monitor_render_platform(ctx: dict) -> dict:
    """Scan our own Render services/deploys for failures and escalate each to an
    auto-fix tracker issue.

    Runs UNSCOPED (platform-level infrastructure, not a single tenant). No-op
    unless error monitoring + the Render scan are enabled and a Render key is set.
    Counts each escalation against the platform company's ``error_escalated`` tally
    when a platform company exists.
    """
    from app.services import error_monitor

    result = await error_monitor.scan_render_platform()
    filed = int(result.get("issues_filed") or 0)
    if filed:
        from app.models.enums import EventType
        from app.services import event_counters, platform_company

        async with SessionLocal() as db:
            company_id = await platform_company.platform_company_id(db)
        if company_id is not None:
            await event_counters.record_standalone(
                company_id=company_id, event_type=EventType.error_escalated, n=filed
            )
    return result


async def optimize_skills(ctx: dict) -> dict:
    """Improve the shared skill library from real outcomes (SkillOpt-style).

    Runs on the platform company's behalf: it aggregates which playbooks are
    underperforming, proposes validation-gated bounded edits, and files them into
    the same triage→implement→auto-merge pipeline a capability request uses. Opt-in
    and no-ops until a platform company is designated and an LLM + tracker exist.
    """
    if not settings.skill_optimize_enabled:
        return {"skipped": True}
    from app.runtime import skill_optimizer
    from app.services import platform_company

    async with SessionLocal() as db:
        company_id = await platform_company.platform_company_id(db)
        if company_id is None:
            return {"skipped": "no_platform_company"}
        await set_tenant(db, company_id)
        result = await skill_optimizer.run(db, ctx["runtime"], company_id=company_id)
        await db.commit()
    return result


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
            # not stack a second, parallel run on top of a live one.
            if await orchestrator.has_active_tasks(db, company_id):
                count += 1
                continue
            task_id = await orchestrator.create_scheduled_run(db, company_id)
            await db.commit()
        count += 1
        if task_id is not None:
            await enqueue_task(task_id)
            enqueued += 1
    return {"companies": count, "enqueued": enqueued}
