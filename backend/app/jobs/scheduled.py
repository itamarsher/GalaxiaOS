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


async def reap_orphaned_approvals_for_company(db, company_id) -> int:
    """Fail the tenant's tasks stuck in ``waiting_approval`` with nothing to resume them.

    A task parks in ``waiting_approval`` when it raises a founder decision OR waits
    for a chat reply. If it lands there with NEITHER a linked ``DecisionRequest`` nor
    a pending ``ChatWait``, it is orphaned: it can never be resolved, its objective is
    blocked, and — because ``waiting_approval`` is an active status — the continuous
    business cycle never winds down, so the whole company silently deadlocks (0 files,
    0 metrics, yet "active"). This fails such tasks (only after a grace window, so a
    just-created decision/wait is never raced), letting the run wind down and the next
    cycle start. The root-cause park-without-a-decision should still be fixed at its
    source; this is the safety net that keeps a company from freezing.

    Operates on the passed (tenant-scoped) session and does NOT commit — the cron
    wrapper owns the transaction. Returns how many tasks it reaped.
    """
    from datetime import UTC, datetime, timedelta

    from app.models import DecisionRequest, Task
    from app.models.enums import TaskStatus
    from app.services import chat as chat_svc

    cutoff = datetime.now(UTC) - timedelta(minutes=settings.orphaned_approval_grace_minutes)
    stuck = (
        await db.scalars(
            select(Task).where(
                Task.company_id == company_id,
                Task.status == TaskStatus.waiting_approval,
                Task.updated_at < cutoff,
            )
        )
    ).all()
    reaped = 0
    for task in stuck:
        # A single linked decision (any status) means this parked to a real decision —
        # leave it (a stuck-after-resolution case is a different bug, and we must not
        # discard approved work). Only a task with NO decision at all AND no pending
        # reply-wait is the orphan we reap.
        has_decision = await db.scalar(
            select(DecisionRequest.id).where(DecisionRequest.task_id == task.id).limit(1)
        )
        if has_decision is not None:
            continue
        if await chat_svc.pending_reply_wait_for_task(db, task_id=task.id) is not None:
            continue
        task.status = TaskStatus.failed
        task.output = {
            **(task.output or {}),
            "error": (
                "Reaped: parked in waiting_approval with no decision or reply-wait "
                "to resume it (would deadlock the company)."
            ),
        }
        reaped += 1
    return reaped


async def reap_orphaned_approvals(ctx: dict) -> dict:
    """Cron: reap orphaned ``waiting_approval`` tasks across every active company."""
    reaped = 0
    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            reaped += await reap_orphaned_approvals_for_company(db, company_id)
            await db.commit()
    return {"reaped": reaped}


async def reap_stale_chat_waits_for_company(db, company_id) -> list:
    """Time out reply-waits that never got an answer, so silence can't deadlock a task.

    A task parks on a ``ChatWait`` when an agent posts a message and waits for a reply
    — from the founder (e.g. ``request_user_action``/``request_decision``) or a
    teammate. The message-budget escalation only catches a *chatty* back-and-forth; a
    wait that simply never gets a reply (the founder is away, a teammate crashed)
    blocks the task forever, and because ``waiting_approval`` is an active status the
    continuous business cycle never winds down. Past a grace window this posts a
    founder-side "no reply — proceed or escalate" note, marks the wait ``expired`` (so
    the task doesn't just re-park on resume, which keys off *pending* waits), and flips
    the task back to ``queued``. Operates on the passed session and does NOT commit;
    returns the woken task ids for the cron to enqueue.
    """
    from datetime import UTC, datetime, timedelta

    from app.models import ChatWait, Task
    from app.models.enums import ChatWaitStatus, TaskStatus
    from app.services import chat as chat_svc

    cutoff = datetime.now(UTC) - timedelta(minutes=settings.chat_reply_timeout_minutes)
    stale = (
        await db.scalars(
            select(ChatWait).where(
                ChatWait.company_id == company_id,
                ChatWait.status == ChatWaitStatus.pending,
                ChatWait.created_at < cutoff,
            )
        )
    ).all()
    woken: list = []
    for wait in stale:
        task = await db.get(Task, wait.task_id)
        # Only unblock a task actually parked on this wait. If the task already moved
        # on (e.g. another of its waits was just resumed) just expire the stale wait.
        if task is None or task.status not in (
            TaskStatus.waiting_approval,
            TaskStatus.running,
        ):
            wait.status = ChatWaitStatus.expired
            continue
        await chat_svc.post_system_reply(
            db,
            company_id=company_id,
            channel_id=wait.channel_id,
            body=(
                f"_(No reply received within {settings.chat_reply_timeout_minutes} minutes.)_ "
                "Proceeding without one — use your best judgment to finish this task, or "
                "escalate to the CEO if you're truly blocked. Do not keep waiting on this thread."
            ),
        )
        wait.status = ChatWaitStatus.expired
        task.status = TaskStatus.queued
        woken.append(task.id)
    return woken


async def reap_stale_chat_waits(ctx: dict) -> dict:
    """Cron: time out unanswered reply-waits across every active company and resume them."""
    from app.runtime.queue import enqueue_task

    to_enqueue: list = []
    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            to_enqueue.extend(await reap_stale_chat_waits_for_company(db, company_id))
            await db.commit()
    for task_id in to_enqueue:
        await enqueue_task(task_id)
    return {"resumed": len(to_enqueue)}


async def keep_warm(ctx: dict) -> dict:
    """Self-ping the public URL so a free-tier host doesn't idle the in-process worker.

    On a host that spins a web service down after inactivity (Render free), the
    in-process think→act worker dies with it and agent cycles stop. A periodic GET to
    the service's own public ``/health`` counts as inbound traffic and resets the idle
    timer, keeping the worker alive. Opt-in via ``ABOS_KEEP_WARM_ENABLED``; a no-op
    without a public URL. Best-effort — a failed ping never raises.
    """
    if not settings.keep_warm_enabled:
        return {"skipped": True}
    base = (settings.public_api_base_url or "").rstrip("/")
    if not base:
        return {"skipped": "no_public_url"}
    import httpx

    url = f"{base}/health"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        return {"pinged": url, "status": resp.status_code}
    except Exception:  # noqa: BLE001 — a keep-warm ping must never break the worker
        return {"pinged": url, "error": True}


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


async def reclaim_expired_initiatives(ctx: dict) -> dict:
    """Reset initiatives whose worker lease expired back to queued (RFC 0001).

    A connected/pull worker claims an initiative (queued → running, with a lease)
    and reports the result; if it crashes mid-flight the lease lapses and the task
    would otherwise be stuck ``running`` forever. This releases those so the next
    worker poll (``get_next_initiative``) re-offers them. Native/push tasks carry no
    lease, so they're never touched. Cheap and idempotent — only expired rows move.
    """
    from app.services import business_function as bf

    released = 0
    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            released += await bf.release_expired_claims(db, company_id=company_id)
            await db.commit()
    return {"released": released}


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
        company_id = platform_company.platform_company_id()
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
        company_id = platform_company.platform_company_id()
        if company_id is None:
            return {"skipped": "no_platform_company"}
        result = await promoter.reconcile_delivered(
            db, company_id=company_id, limit=settings.platform_reconcile_batch
        )
        await db.commit()
    return result


async def triage_founder_decisions(ctx: dict) -> dict:
    """Route each pending founder decision by human involvement, and notify the
    founder's webhooks (see app.services.delegate + involvement_router).

    Runs per active company. The involvement router decides whether a decision
    goes to a human (escalate) or is auto-approved so agents proceed; the delegate
    config, when present, only supplies the notification channels. Heavy work (the
    routing LLM call, the webhook POST) is kept off the agent hot path — this cron
    is its own place. Auto-resolutions go through the normal decision-resolution
    path, so their resumed tasks are enqueued exactly like a founder's click.
    """
    if not settings.delegate_enabled:
        return {"skipped": True}
    from app.runtime.queue import enqueue_task
    from app.services import delegate
    from app.services import telegram as telegram_svc

    to_enqueue: list = []
    webhooks: list[tuple[str, dict, str | None]] = []  # (url, payload, secret)
    telegrams: list[tuple[str, str]] = []  # (chat_id, text)
    handled = 0

    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            company = await db.get(Company, company_id)
            if company is None:
                continue
            # The delegate config is notification-only now (may be absent); routing
            # runs for every active company off the members' involvement prose.
            cfg = await delegate.get_config(db, company_id)
            for decision in await delegate.untriaged_pending(db, company_id):
                outcome = await delegate.handle(
                    db, company=company, decision=decision, cfg=cfg
                )
                handled += 1
                if outcome.resumed_task_id is not None:
                    to_enqueue.append(outcome.resumed_task_id)
                if outcome.webhook_payload is not None and cfg is not None:
                    for target in cfg.webhooks:
                        if delegate.webhook_wants(target.events, outcome.disposition):
                            webhooks.append(
                                (target.url, outcome.webhook_payload, cfg.signing_secret)
                            )
                    if (
                        cfg.telegram_chat_id
                        and telegram_svc.enabled()
                        and delegate.webhook_wants(cfg.telegram_events, outcome.disposition)
                    ):
                        telegrams.append(
                            (cfg.telegram_chat_id, telegram_svc.format_decision(outcome.webhook_payload))
                        )
            await db.commit()

    # Fire side effects only after the DB is durably committed.
    from app.services import delegate as _delegate

    for task_id in to_enqueue:
        await enqueue_task(task_id)
    for url, payload, secret in webhooks:
        await _delegate.send_webhook(url, payload, secret)
    for chat_id, text in telegrams:
        await telegram_svc.send_message(chat_id, text)
    return {
        "handled": handled,
        "resumed": len(to_enqueue),
        "notified": len(webhooks) + len(telegrams),
    }


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
        company_id = platform_company.platform_company_id()
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

        company_id = platform_company.platform_company_id()
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
        company_id = platform_company.platform_company_id()
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
