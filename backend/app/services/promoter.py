"""The promoter: demand backlog → tracker issues, and back again on delivery.

This is the automation that makes Galaxia's dogfooding loop *run on its own*
rather than only when a human prompts the Platform agent:

- :func:`promote_backlog` drains the shared feature-request backlog into real
  tracker issues (highest-demand first), filing each through the same GitHub seam
  the Platform agent uses. A scheduled cron calls it on Galaxia's behalf.
- :func:`reconcile_delivered` closes the loop: for every promoted entry whose
  tracker issue has since closed (its fix merged), it flips the entry to
  ``delivered`` and writes a notice to each company that requested it — so agents
  learn the gap they reported is now closed instead of re-requesting it forever.

The single-entry :func:`promote_request` is shared with the Platform agent's
``promote_feature_request`` tool so interactive and scheduled promotion behave
identically. Issue-tracker resolution (:func:`resolve_issue_tracker`) also lives
here so the tool and the crons agree on which tracker a company files against.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.issues import (
    GitHubIssueTracker,
    IssueTracker,
    IssueTrackerError,
    get_issue_tracker,
)
from app.models import FeatureRequest
from app.models.enums import FeatureRequestKind, MemoryType
from app.observability import get_logger
from app.services import apikeys
from app.services import feature_requests as fr_svc
from app.services import memory as memory_svc

_log = get_logger("abos.promoter")

#: Provider name under which a company's GitHub token is stored (BYOK).
GITHUB_PROVIDER = "github"

#: Maps a backlog kind to the tracker label used when filing.
KIND_LABEL = {
    FeatureRequestKind.bug: "bug",
    FeatureRequestKind.capability: "enhancement",
}


async def resolve_issue_tracker(db: AsyncSession, company_id: uuid.UUID) -> IssueTracker | None:
    """The company's own GitHub tracker if it set a token, else the global default.

    Returns ``None`` when no tracker is configured (no per-company token and no
    global ``ABOS_GITHUB_TOKEN``), so callers skip rather than 401 against GitHub.
    """
    token = await apikeys.get_plaintext_key(
        db, company_id=company_id, provider=GITHUB_PROVIDER
    )
    if token:
        return GitHubIssueTracker(token, repo=settings.github_repo)
    return get_issue_tracker()


@dataclass(frozen=True)
class PromotionResult:
    feature_id: uuid.UUID
    title: str
    number: int
    url: str
    provider: str
    created: bool
    demand: int


async def promote_request(
    db: AsyncSession,
    *,
    fr: FeatureRequest,
    tracker: IssueTracker,
    company_id: uuid.UUID,
    source_task_id: uuid.UUID | None = None,
) -> PromotionResult:
    """File one backlog entry as a tracker issue, mark it promoted, audit to memory.

    Raises :class:`IssueTrackerError` if the tracker call fails (caller decides
    whether to stop the batch). Shared by the Platform agent's tool and the cron.
    """
    body = await fr_svc.build_issue_body(db, fr)
    label = KIND_LABEL.get(fr.kind, "enhancement")
    result = await tracker.report_issue(title=fr.title, body=body, labels=[label])
    await fr_svc.mark_promoted(db, fr, issue_number=result.number, issue_url=result.url)
    await memory_svc.write(
        db,
        company_id=company_id,
        type=MemoryType.result,
        title=f"Feature request promoted: {fr.title[:80]}",
        content=(
            f"Backlog entry {fr.id} ({fr.vote_count} vote(s)) "
            f"{'filed as' if result.created else 'matched existing'} issue "
            f"#{result.number} via {result.provider}.\nURL: {result.url}\n\n{body}"
        ),
        source_task_id=source_task_id,
    )
    return PromotionResult(
        feature_id=fr.id,
        title=fr.title,
        number=result.number,
        url=result.url,
        provider=result.provider,
        created=result.created,
        demand=result.demand,
    )


async def promote_backlog(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    min_votes: int,
    limit: int,
) -> dict:
    """Promote up to ``limit`` open backlog entries with ≥ ``min_votes`` demand.

    Files highest-demand first. Stops the batch on the first tracker error (a
    tracker outage shouldn't burn the whole queue) and reports what it did.
    """
    tracker = await resolve_issue_tracker(db, company_id)
    if tracker is None:
        return {"promoted": 0, "considered": 0, "skipped": "no_tracker"}

    entries = await fr_svc.list_open(db, min_votes=min_votes, limit=limit)
    promoted: list[str] = []
    for fr in entries:
        try:
            result = await promote_request(
                db, fr=fr, tracker=tracker, company_id=company_id
            )
        except IssueTrackerError:
            _log.exception("promote_backlog: tracker error on %s; stopping batch", fr.id)
            break
        promoted.append(result.url)
    return {"promoted": len(promoted), "considered": len(entries), "urls": promoted}


async def reconcile_delivered(
    db: AsyncSession, *, company_id: uuid.UUID, limit: int
) -> dict:
    """Mark promoted entries delivered once their tracker issue has closed.

    For each promoted entry, ask the tracker for the issue state; when it is
    ``closed`` (the fix merged), flip the entry to ``delivered`` and write a
    delivery notice into each requesting company's memory. Read-only against the
    tracker; a missing/erroring state simply leaves the entry promoted for a retry.
    """
    tracker = await resolve_issue_tracker(db, company_id)
    if tracker is None:
        return {"delivered": 0, "checked": 0, "skipped": "no_tracker"}
    if not hasattr(tracker, "get_issue_state"):
        return {"delivered": 0, "checked": 0, "skipped": "tracker_unsupported"}

    entries = await fr_svc.list_promoted(db, limit=limit)
    delivered = 0
    for fr in entries:
        state = await tracker.get_issue_state(fr.github_issue_number)
        if state != "closed":
            continue
        await fr_svc.mark_delivered(db, fr)
        await _notify_requesters(db, fr)
        delivered += 1
    return {"delivered": delivered, "checked": len(entries)}


async def _notify_requesters(db: AsyncSession, fr: FeatureRequest) -> None:
    """Write a 'your requested capability shipped' notice to each requester."""
    company_ids = await fr_svc.requesting_company_ids(db, fr.id)
    ref = (
        f"issue #{fr.github_issue_number}"
        + (f" ({fr.github_issue_url})" if fr.github_issue_url else "")
    )
    noun = "bug fix" if fr.kind is FeatureRequestKind.bug else "capability"
    for cid in company_ids:
        await memory_svc.write(
            db,
            company_id=cid,
            type=MemoryType.result,
            title=f"Delivered: {fr.title[:80]}",
            content=(
                f"The {noun} your team requested — {fr.title!r} — has shipped: {ref} "
                "was closed (its fix merged). If a tool you were waiting on is now "
                "available, retry the work that was blocked; there is no need to "
                "request this again."
            ),
            structured={"kind": "capability_delivered", "feature_request_id": str(fr.id)},
        )
