"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import (
    apikeys,
    auth,
    budget,
    companies,
    copilot,
    decisions,
    events,
    governance,
    marketplace,
    onboarding,
)
from app.config import settings
from app.db import SessionLocal
from app.observability import RequestContextMiddleware, configure_logging
from app.ratelimit import RateLimitMiddleware, build_limiter


def create_app() -> FastAPI:
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    app = FastAPI(title="ABOS — Autonomous Business Operating System", version="0.1.0")

    # Middleware added later is outermost: request-context wraps everything (so
    # rate-limit rejections and CORS are logged with a request id).
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    if settings.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware, limiter=build_limiter())
    app.add_middleware(RequestContextMiddleware)

    app.include_router(auth.router)
    app.include_router(onboarding.router)
    app.include_router(apikeys.router)
    app.include_router(companies.router)
    app.include_router(budget.router)
    app.include_router(governance.router)
    app.include_router(decisions.router)
    app.include_router(copilot.router)
    app.include_router(events.router)
    app.include_router(marketplace.catalog_router)
    app.include_router(marketplace.company_router)

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
