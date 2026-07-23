"""Launching a company requires a connected storage provider.

A company can't function without a file store — agents file every report and
artifact there — so ``onboarding.launch`` refuses to activate a company that has
no storage, for an AI operator (Founder MCP) exactly as for a human founder. The
guard only bites where storage *can* be connected (the Drive OAuth app is
configured on the deployment); otherwise it's skipped so it's never a dead end.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.integrations import gdrive_oauth
from app.models import Company
from app.services import onboarding
from app.services.onboarding import OnboardingError
from tests.conftest import requires_db

pytestmark = requires_db


class _PastGuard(Exception):
    """Sentinel raised just after the storage guard to prove it was skipped."""


@requires_db
async def test_launch_blocks_without_storage(session_factory, company_with_budget, monkeypatch):
    async def _no_provider(db, *, company_id):
        return None

    monkeypatch.setattr(gdrive_oauth, "connect_configured", lambda: True)
    monkeypatch.setattr(
        "app.services.integrations.resolve_file_provider", _no_provider
    )
    monkeypatch.setattr(settings, "require_storage_to_launch", True)

    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        with pytest.raises(OnboardingError) as ei:
            await onboarding.launch(db, company=company)
    assert "storage" in str(ei.value).lower()


@requires_db
async def test_launch_skips_guard_when_storage_cannot_be_connected(
    session_factory, company_with_budget, monkeypatch
):
    """No Drive OAuth app on the deployment → the requirement is skipped, not fatal."""

    async def _no_provider(db, *, company_id):
        return None

    def _boom():
        raise _PastGuard()

    monkeypatch.setattr(gdrive_oauth, "connect_configured", lambda: False)
    monkeypatch.setattr(
        "app.services.integrations.resolve_file_provider", _no_provider
    )
    monkeypatch.setattr(settings, "require_storage_to_launch", True)
    # Prove control flow reaches past the storage guard (into the launch body).
    monkeypatch.setattr(onboarding.gov, "default_policies", _boom)

    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        with pytest.raises(_PastGuard):
            await onboarding.launch(db, company=company)
