"""Per-company GitHub token + key management (Settings / onboarding optional key).

The GitHub token is stored like any BYOK key (provider="github", envelope
encrypted). When present, the platform agent files real GitHub issues; otherwise
it falls back to the configured default tracker. Founders can also revoke keys.
"""

from __future__ import annotations

import base64
import os

from app.integrations.issues import GitHubIssueTracker, get_issue_tracker
from app.runtime.tools.platform import GITHUB_PROVIDER, _resolve_issue_tracker
from app.services import apikeys
from tests.conftest import requires_db


def _set_master_key() -> None:
    from app.config import settings as app_settings

    app_settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


@requires_db
async def test_issue_tracker_is_none_without_any_github_token(
    session_factory, company_with_budget
):
    _set_master_key()
    async with session_factory() as db:
        tracker = await _resolve_issue_tracker(db, company_with_budget)
    # GitHub is the default tracker, but with neither a per-company key nor a global
    # ABOS_GITHUB_TOKEN there's nothing to authenticate with -> None, so open_issue
    # records the request to company memory instead of 401-ing against GitHub.
    assert tracker is None


def test_global_github_token_enables_github_without_explicit_tracker(monkeypatch):
    """A configured global ABOS_GITHUB_TOKEN files real issues on its own.

    Regression: with the tracker left at its default ("simulated") a deployment
    that set only the token used to fall back to None, so the Platform agent told
    agents the GitHub token "wasn't set" when it was.
    """
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "issue_tracker", "simulated")
    monkeypatch.setattr(app_settings, "github_token", "ghp_globaltoken")
    assert isinstance(get_issue_tracker(), GitHubIssueTracker)


def test_explicit_none_disables_github_even_with_global_token(monkeypatch):
    """``ABOS_ISSUE_TRACKER=none`` is a hard opt-out even if a token is present."""
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "issue_tracker", "none")
    monkeypatch.setattr(app_settings, "github_token", "ghp_globaltoken")
    assert get_issue_tracker() is None


def test_no_tracker_without_any_github_token(monkeypatch):
    """Default + no token -> None (records to memory, never fabricates an issue)."""
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "issue_tracker", "simulated")
    monkeypatch.setattr(app_settings, "github_token", "")
    assert get_issue_tracker() is None


@requires_db
async def test_resolve_issue_tracker_falls_back_to_global_token(
    session_factory, company_with_budget, monkeypatch
):
    """No per-company key but a global token still resolves to a real tracker."""
    from app.config import settings as app_settings

    _set_master_key()
    monkeypatch.setattr(app_settings, "issue_tracker", "simulated")
    monkeypatch.setattr(app_settings, "github_token", "ghp_globaltoken")
    async with session_factory() as db:
        tracker = await _resolve_issue_tracker(db, company_with_budget)
    assert isinstance(tracker, GitHubIssueTracker)


@requires_db
async def test_issue_tracker_uses_github_when_company_key_set(
    session_factory, company_with_budget
):
    _set_master_key()
    async with session_factory() as db:
        await apikeys.store_key(
            db, company_id=company_with_budget, provider=GITHUB_PROVIDER, plaintext="ghp_testtoken"
        )
        await db.commit()
    async with session_factory() as db:
        tracker = await _resolve_issue_tracker(db, company_with_budget)
    assert isinstance(tracker, GitHubIssueTracker)


@requires_db
async def test_github_key_does_not_disturb_llm_provider_resolution(
    session_factory, company_with_budget
):
    """A github key must not be picked as the LLM provider key."""
    _set_master_key()
    async with session_factory() as db:
        await apikeys.store_key(
            db, company_id=company_with_budget, provider=GITHUB_PROVIDER, plaintext="ghp_testtoken"
        )
        await db.commit()
        # Only a github key exists -> no usable LLM provider.
        assert await apikeys.resolve_provider(db, company_id=company_with_budget) is None


@requires_db
async def test_revoke_key_removes_it_from_active_list(session_factory, company_with_budget):
    _set_master_key()
    async with session_factory() as db:
        key = await apikeys.store_key(
            db, company_id=company_with_budget, provider="anthropic", plaintext="sk-ant-xxxx"
        )
        await db.commit()
        key_id = key.id

    async with session_factory() as db:
        assert await apikeys.revoke_key(db, company_id=company_with_budget, key_id=key_id) is True
        await db.commit()

    async with session_factory() as db:
        active = await apikeys.list_keys(db, company_id=company_with_budget)
        assert all(k.id != key_id for k in active)
        # Revoking something that isn't there is a no-op (False), not an error.
        assert await apikeys.revoke_key(db, company_id=company_with_budget, key_id=key_id) is False
