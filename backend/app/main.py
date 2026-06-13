"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


def create_app() -> FastAPI:
    app = FastAPI(title="ABOS — Autonomous Business Operating System", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    return app


app = create_app()
