"""The scheduled promoter and the loop-closing reconciler (P0-2 + P1-5).

promote_backlog drains the shared feature-request backlog into tracker issues
without waiting for a human; reconcile_delivered flips a promoted entry to
``delivered`` once its issue closes and notifies the companies that asked. Both
are exercised here against real Postgres with a fake tracker; memory writes are
stubbed (the pgvector memory table is excluded from the test schema).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.integrations.issues import IssueResult, IssueTrackerError
from app.models import Company, FeatureRequest, User
from app.models.enums import CompanyStatus, FeatureRequestStatus
from app.services import feature_requests as fr_svc
from app.services import promoter
from tests.conftest import requires_db


async def _company(db, name="Req") -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(user)
    await db.flush()
    company = Company(owner_user_id=user.id, name=name, status=CompanyStatus.active)
    db.add(company)
    await db.flush()
    return company.id


class _FakeTracker:
    """Records filed issues and answers get_issue_state from a scripted map."""

    def __init__(self, states: dict[int, str] | None = None):
        self.filed: list[tuple[str, list | None]] = []
        self._states = states or {}
        self._next_number = 100

    async def report_issue(self, *, title, body, labels=None):
        self._next_number += 1
        self.filed.append((title, labels))
        return IssueResult(
            id="x", number=self._next_number, url=f"https://gh/i/{self._next_number}",
            provider="github", created=True, demand=1,
        )

    async def get_issue_state(self, number: int) -> str | None:
        return self._states.get(number)


@requires_db
async def test_promote_backlog_files_issues_and_marks_promoted(session_factory, monkeypatch):
    tracker = _FakeTracker()
    monkeypatch.setattr(promoter, "resolve_issue_tracker", lambda db, cid: _ret(tracker))
    monkeypatch.setattr("app.services.memory.write", _noop)

    async with session_factory() as db:
        galaxia_id = await _company(db, "Galaxia")
        c1 = await _company(db, "Acme")
        c2 = await _company(db, "Beta")
        # Two entries: one with 2 votes, one with 1.
        await fr_svc.record_request(db, kind="capability", title="Slack tool",
                                    details="post updates", company_id=c1)
        await fr_svc.record_request(db, kind="capability", title="Slack tool",
                                    details="post updates", company_id=c2)
        await fr_svc.record_request(db, kind="bug", title="io crash",
                                    details="500s", company_id=c1)
        await db.commit()

    async with session_factory() as db:
        result = await promoter.promote_backlog(
            db, company_id=galaxia_id, min_votes=1, limit=10
        )
        await db.commit()

    assert result["promoted"] == 2
    assert result["considered"] == 2
    # Highest-demand first: the 2-vote "Slack tool" is filed before the 1-vote bug.
    assert tracker.filed[0][0] == "Slack tool"
    assert tracker.filed[0][1] == ["enhancement"]  # capability -> enhancement label
    assert ("io crash", ["bug"]) in tracker.filed

    async with session_factory() as db:
        frs = (await db.scalars(select(FeatureRequest))).all()
    assert all(fr.status is FeatureRequestStatus.promoted for fr in frs)
    assert all(fr.github_issue_number is not None for fr in frs)


@requires_db
async def test_promote_backlog_respects_min_votes(session_factory, monkeypatch):
    tracker = _FakeTracker()
    monkeypatch.setattr(promoter, "resolve_issue_tracker", lambda db, cid: _ret(tracker))
    monkeypatch.setattr("app.services.memory.write", _noop)

    async with session_factory() as db:
        galaxia_id = await _company(db, "Galaxia")
        c1 = await _company(db, "Acme")
        await fr_svc.record_request(db, kind="capability", title="only one vote",
                                    details="x", company_id=c1)
        await db.commit()

    async with session_factory() as db:
        result = await promoter.promote_backlog(
            db, company_id=galaxia_id, min_votes=2, limit=10
        )
        await db.commit()

    assert result["promoted"] == 0
    assert tracker.filed == []


@requires_db
async def test_promote_backlog_skips_when_no_tracker(session_factory, monkeypatch):
    monkeypatch.setattr(promoter, "resolve_issue_tracker", lambda db, cid: _ret(None))
    async with session_factory() as db:
        galaxia_id = await _company(db, "Galaxia")
        result = await promoter.promote_backlog(db, company_id=galaxia_id, min_votes=1, limit=5)
    assert result["skipped"] == "no_tracker"


@requires_db
async def test_promote_backlog_stops_on_tracker_error(session_factory, monkeypatch):
    class _Boom:
        async def report_issue(self, **_):
            raise IssueTrackerError("gh down")

    monkeypatch.setattr(promoter, "resolve_issue_tracker", lambda db, cid: _ret(_Boom()))
    monkeypatch.setattr("app.services.memory.write", _noop)
    async with session_factory() as db:
        galaxia_id = await _company(db, "Galaxia")
        c1 = await _company(db, "Acme")
        await fr_svc.record_request(db, kind="bug", title="x", details="y", company_id=c1)
        await db.commit()
    async with session_factory() as db:
        result = await promoter.promote_backlog(db, company_id=galaxia_id, min_votes=1, limit=5)
    assert result["promoted"] == 0  # errored before any success


@requires_db
async def test_reconcile_marks_delivered_and_notifies_requesters(session_factory, monkeypatch):
    # Issue #55 is closed (merged); #56 is still open.
    tracker = _FakeTracker(states={55: "closed", 56: "open"})
    monkeypatch.setattr(promoter, "resolve_issue_tracker", lambda db, cid: _ret(tracker))

    notices: list[dict] = []

    async def _capture(db, **kwargs):
        notices.append(kwargs)
        return None

    monkeypatch.setattr("app.services.memory.write", _capture)

    async with session_factory() as db:
        galaxia_id = await _company(db, "Galaxia")
        c1 = await _company(db, "Acme")
        c2 = await _company(db, "Beta")
        # Closed request, wanted by two companies.
        out1 = await fr_svc.record_request(db, kind="capability", title="shipped thing",
                                           details="x", company_id=c1)
        await fr_svc.record_request(db, kind="capability", title="shipped thing",
                                    details="x", company_id=c2)
        out2 = await fr_svc.record_request(db, kind="bug", title="still open",
                                           details="y", company_id=c1)
        fr1 = await fr_svc.get(db, out1.feature_id)
        fr2 = await fr_svc.get(db, out2.feature_id)
        await fr_svc.mark_promoted(db, fr1, issue_number=55, issue_url="https://gh/i/55")
        await fr_svc.mark_promoted(db, fr2, issue_number=56, issue_url="https://gh/i/56")
        await db.commit()

    async with session_factory() as db:
        result = await promoter.reconcile_delivered(db, company_id=galaxia_id, limit=25)
        await db.commit()

    assert result["delivered"] == 1
    assert result["checked"] == 2

    async with session_factory() as db:
        fr1 = await db.get(FeatureRequest, out1.feature_id)
        fr2 = await db.get(FeatureRequest, out2.feature_id)
    assert fr1.status is FeatureRequestStatus.delivered
    assert fr2.status is FeatureRequestStatus.promoted  # issue still open

    # Both requesting companies were notified about the delivered one.
    notified = {n["company_id"] for n in notices}
    assert notified == {c1, c2}
    assert all(n["structured"]["kind"] == "capability_delivered" for n in notices)


# ── tiny async helpers (awaitables for monkeypatched coroutine functions) ──────


async def _ret(value):
    return value


async def _noop(db, **kwargs):
    return None
