"""System-wide error monitoring: escalation, dedup, and the Render scan (offline)."""

from __future__ import annotations

import pytest

from app.config import settings
from app.integrations.issues import IssueResult
from app.integrations.render import RenderDeploy, RenderService
from app.services import error_monitor as em


class _FakeTracker:
    def __init__(self) -> None:
        self.filed: list[tuple[str, list | None]] = []

    async def report_issue(self, *, title, body, labels=None):
        self.filed.append((title, labels))
        return IssueResult(id="1", number=7, url="https://gh/x/7", provider="github", created=True)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    em.reset_dedup_cache()
    monkeypatch.setattr(settings, "error_monitor_enabled", True)
    monkeypatch.setattr(settings, "error_monitor_labels", "bug,auto-detected")
    yield
    em.reset_dedup_cache()


@pytest.mark.asyncio
async def test_report_code_error_files_once_then_dedupes(monkeypatch):
    tracker = _FakeTracker()
    monkeypatch.setattr(em, "get_issue_tracker", lambda name=None: tracker)

    filed = await em.report_code_error(
        error_type="ValueError", message="bad id 42", where="abos.access",
        traceback_text="Traceback...\nValueError: bad id 42",
    )
    assert filed is True
    assert tracker.filed[0][0] == "[auto] ValueError in abos.access"
    assert tracker.filed[0][1] == ["bug", "auto-detected"]

    # Same fingerprint (volatile id differs) within cooldown → not refiled.
    again = await em.report_code_error(
        error_type="ValueError", message="bad id 99", where="abos.access",
    )
    assert again is False
    assert len(tracker.filed) == 1


@pytest.mark.asyncio
async def test_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "error_monitor_enabled", False)
    tracker = _FakeTracker()
    monkeypatch.setattr(em, "get_issue_tracker", lambda name=None: tracker)
    assert await em.report_code_error(error_type="X", message="y", where="z") is False
    assert tracker.filed == []


@pytest.mark.asyncio
async def test_no_tracker_is_noop(monkeypatch):
    monkeypatch.setattr(em, "get_issue_tracker", lambda name=None: None)
    assert await em.report_code_error(error_type="X", message="y", where="z") is False


class _FakeRenderClient:
    def __init__(self, services, deploys) -> None:
        self._services = services
        self._deploys = deploys

    async def list_services(self, *, limit=50):
        return self._services

    async def list_deploys(self, service_id, *, limit=5):
        return self._deploys.get(service_id, [])


def _svc(sid, suspended="not_suspended"):
    return RenderService(
        id=sid, name=f"n-{sid}", type="web_service", suspended=suspended, dashboard_url="d"
    )


def _deploy(status):
    return RenderDeploy(
        id="dep1", status=status, commit_id="abc123", commit_message="m",
        created_at="", finished_at="",
    )


@pytest.mark.asyncio
async def test_render_scan_files_for_failed_deploy_and_suspended(monkeypatch):
    tracker = _FakeTracker()
    services = [_svc("srv-ok"), _svc("srv-bad"), _svc("srv-susp", suspended="suspended")]
    deploys = {
        "srv-ok": [_deploy("live")],
        "srv-bad": [_deploy("build_failed")],
        "srv-susp": [_deploy("live")],
    }
    monkeypatch.setattr(em, "get_render_client", lambda: _FakeRenderClient(services, deploys))
    monkeypatch.setattr(em, "get_issue_tracker", lambda name=None: tracker)

    result = await em.scan_render_platform()
    assert result["services"] == 3
    assert result["issues_filed"] == 2  # one failed deploy + one suspended
    titles = sorted(t for t, _ in tracker.filed)
    assert any("deploy failed" in t.lower() for t in titles)
    assert any("suspended" in t.lower() for t in titles)


@pytest.mark.asyncio
async def test_render_scan_skips_without_key(monkeypatch):
    monkeypatch.setattr(em, "get_render_client", lambda: None)
    monkeypatch.setattr(em, "get_issue_tracker", lambda name=None: _FakeTracker())
    result = await em.scan_render_platform()
    assert result["skipped"] == "no_render_key"
    assert result["issues_filed"] == 0
