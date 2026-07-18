"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import (
    apikeys,
    artifacts,
    auth,
    bf_mcp,
    billing,
    budget,
    chat,
    comms,
    companies,
    copilot,
    decisions,
    delegate,
    domains,
    events,
    files,
    governance,
    integrations,
    marketplace,
    mcp,
    metrics,
    onboarding,
    public,
    stripe_webhooks,
    webhooks_telegram,
)
from app.config import settings
from app.db import SessionLocal
from app.observability import RequestContextMiddleware, configure_logging
from app.providers.base import ProviderError
from app.ratelimit import RateLimitMiddleware, build_limiter
from app.services.budget import BudgetExceeded


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Optionally run the arq worker in-process (single-instance / free-tier).

    In production the worker is a separate service and this is a no-op. When
    ``ABOS_RUN_WORKER_IN_PROCESS`` is set, the think→act loop and cron jobs run
    as a background task alongside the API so the whole app fits on one host.
    """
    # The dogfooding company is no longer synthesized at startup. It is a real
    # company the founder onboards: the first company created in a deployment is
    # flagged as the platform company (services/platform_company.py), which is what
    # authorizes the Platform agent's promoter tools and drives the demand→issue
    # loop. The promoter/render/cron gates all key off that flag.
    # Point the shared Telegram bot at our inbound webhook so founders' connect
    # deep links resolve. Best-effort and idempotent; no-op without a bot token.
    if settings.telegram_bot_token and settings.public_api_base_url:
        from app.services import telegram as telegram_svc

        with contextlib.suppress(Exception):
            await telegram_svc.ensure_webhook(settings.public_api_base_url)

    worker = None
    task = None
    if settings.run_worker_in_process:
        # Imported lazily so the API has no hard dependency on the worker wiring.
        from app.runtime.worker import build_worker

        worker = build_worker(handle_signals=False)
        task = asyncio.create_task(worker.async_run())
        logging.getLogger("app").info("in-process arq worker started")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if worker is not None:
            await worker.close()


def create_app() -> FastAPI:
    configure_logging(
        level=settings.log_level,
        json_logs=settings.log_json,
        escalate_errors=settings.error_monitor_enabled,
    )
    app = FastAPI(
        title="ABOS — Autonomous Business Operating System",
        version="0.1.0",
        lifespan=_lifespan,
    )

    # Middleware added later is outermost. Order (inner → outer):
    # rate-limit → request-context → CORS. CORS is outermost so that *every*
    # response carries the Access-Control-* headers — including the rate
    # limiter's 429 rejections and error responses. If CORS sat inside the
    # rate limiter, a rejected request would come back with no CORS header and
    # the browser would mask the real status with an opaque
    # "No 'Access-Control-Allow-Origin' header is present" error. Request
    # context still wraps the rate limiter, so rejections are logged with a
    # request id.
    if settings.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware, limiter=build_limiter())
    app.add_middleware(RequestContextMiddleware)
    cors_origins = settings.cors_allow_origins
    allow_all_origins = "*" in cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        # A wildcard origin can't be combined with credentials per the CORS
        # spec, and the frontend authenticates with a bearer token rather than
        # cookies — so only enable credentials for an explicit allowlist.
        allow_credentials=not allow_all_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(public.router)
    app.include_router(stripe_webhooks.router)
    app.include_router(onboarding.router)
    app.include_router(apikeys.router)
    app.include_router(integrations.router)
    app.include_router(integrations.callback_router)
    app.include_router(files.router)
    app.include_router(mcp.router)
    app.include_router(bf_mcp.router)
    app.include_router(bf_mcp.mint_router)
    app.include_router(artifacts.router)
    app.include_router(companies.router)
    app.include_router(companies.mine_router)
    app.include_router(domains.router)
    app.include_router(budget.router)
    app.include_router(governance.router)
    app.include_router(metrics.router)
    app.include_router(decisions.router)
    app.include_router(delegate.router)
    app.include_router(webhooks_telegram.router)
    app.include_router(comms.router)
    app.include_router(chat.router)
    app.include_router(copilot.router)
    app.include_router(billing.router)
    app.include_router(events.router)
    app.include_router(marketplace.catalog_router)
    app.include_router(marketplace.company_router)

    @app.exception_handler(ProviderError)
    async def _provider_error(request: Request, exc: ProviderError) -> JSONResponse:
        """Surface upstream LLM-provider failures as a clear 502 instead of a
        bare 500. Registered handlers run inside the CORS layer, so the response
        carries the Access-Control-* headers."""
        return JSONResponse(
            {"detail": str(exc), "kind": exc.kind},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    @app.exception_handler(BudgetExceeded)
    async def _budget_exceeded(request: Request, exc: BudgetExceeded) -> JSONResponse:
        """A reservation over the company/agent budget is an expected business
        condition (e.g. generating an org with too small a budget), not a server
        fault — return 402 with the shortfall instead of a 500."""
        return JSONResponse(
            {
                "detail": str(exc),
                "scope": exc.scope,
                "requested_cents": exc.requested_cents,
                "available_cents": exc.available_cents,
            },
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
        )

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["meta"])
    async def ready():
        """Readiness probe: confirms the database is reachable."""
        try:
            async with SessionLocal() as db:
                await db.execute(text("SELECT 1"))
            return {"status": "ready", "db": "ok"}
        except Exception as exc:  # noqa: BLE001
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {"status": "degraded", "db": f"error: {type(exc).__name__}"}, status_code=503
            )

    return app


app = create_app()
