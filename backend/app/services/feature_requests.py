"""The internal feature-request backlog: record demand, dedup, and promote.

This is the seam between "someone asked for X" and "a tracker issue exists for X".
Every ``request_capability`` / ``report_bug`` lands here via :func:`record_request`,
which deduplicates by a normalized key and accrues one vote per (company, user) —
so repeated asks become a demand signal, not duplicate rows. A gated promoter in
the abos company later reads the backlog (:func:`list_open`) and files the real
tracker issue, then calls :func:`mark_promoted` to record the issue number.

Dedup + voting mirror what the GitHub tracker already does on its side (one issue
per title, "+1" comments tally demand); doing it here too means the demand signal
exists *before* anything is filed, and survives offline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, FeatureRequest, FeatureRequestVote, User
from app.models.enums import FeatureRequestKind, FeatureRequestStatus


@dataclass(frozen=True)
class RequestOutcome:
    """The result of recording a request — enough to phrase a user-facing reply."""

    feature_id: uuid.UUID
    kind: FeatureRequestKind
    title: str
    votes: int
    #: ``True`` when this opened a brand-new backlog entry (vs. +1'ing an existing).
    is_new_feature: bool
    #: ``True`` when this (company, user) had not already voted for it.
    is_new_vote: bool
    status: FeatureRequestStatus


def coerce_kind(kind: str | FeatureRequestKind) -> FeatureRequestKind | None:
    """Map a loose kind ('bug'/'capability'/enum) to the enum, or ``None``."""
    if isinstance(kind, FeatureRequestKind):
        return kind
    try:
        return FeatureRequestKind(str(kind).strip().lower())
    except ValueError:
        return None


def _dedup_key(kind: FeatureRequestKind, title: str) -> str:
    """Normalize ``kind`` + ``title`` into the dedup key (case/whitespace-insensitive)."""
    collapsed = " ".join(title.split()).lower()
    return f"{kind.value}:{collapsed}"[:560]


async def record_request(
    db: AsyncSession,
    *,
    kind: str | FeatureRequestKind,
    title: str,
    details: str,
    company_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> RequestOutcome | None:
    """Record a capability/bug request, deduped by title and voted per company/user.

    Returns ``None`` if the kind is unknown or the title is empty. A repeat ask
    from the same (company, user) refreshes that vote's details instead of adding
    another vote, so ``vote_count`` is honest demand.
    """
    fk = coerce_kind(kind)
    if fk is None:
        return None
    title = title.strip()
    details = details.strip()
    if not title:
        return None

    key = _dedup_key(fk, title)
    fr = await db.scalar(select(FeatureRequest).where(FeatureRequest.dedup_key == key))
    is_new_feature = fr is None
    if fr is None:
        fr = FeatureRequest(
            kind=fk,
            title=title[:500],
            dedup_key=key,
            details=details or title,
            status=FeatureRequestStatus.open,
            vote_count=0,
        )
        db.add(fr)
        await db.flush()

    # One vote per (request, company, user). ``user_id is None`` (agent/system)
    # collapses to a single per-company vote via the IS NULL match below.
    existing_vote = await db.scalar(
        select(FeatureRequestVote).where(
            FeatureRequestVote.feature_request_id == fr.id,
            FeatureRequestVote.company_id == company_id,
            FeatureRequestVote.user_id == user_id,
        )
    )
    is_new_vote = existing_vote is None
    if existing_vote is None:
        db.add(
            FeatureRequestVote(
                feature_request_id=fr.id,
                company_id=company_id,
                user_id=user_id,
                details=details or None,
            )
        )
        fr.vote_count = (fr.vote_count or 0) + 1
    elif details:
        existing_vote.details = details

    await db.flush()
    return RequestOutcome(
        feature_id=fr.id,
        kind=fr.kind,
        title=fr.title,
        votes=fr.vote_count,
        is_new_feature=is_new_feature,
        is_new_vote=is_new_vote,
        status=fr.status,
    )


async def list_open(
    db: AsyncSession,
    *,
    kind: FeatureRequestKind | None = None,
    min_votes: int = 1,
    limit: int = 50,
) -> list[FeatureRequest]:
    """Open backlog entries, most-demanded first (then oldest), for the promoter."""
    stmt = (
        select(FeatureRequest)
        .where(
            FeatureRequest.status == FeatureRequestStatus.open,
            FeatureRequest.vote_count >= min_votes,
        )
        .order_by(FeatureRequest.vote_count.desc(), FeatureRequest.created_at.asc())
        .limit(limit)
    )
    if kind is not None:
        stmt = stmt.where(FeatureRequest.kind == kind)
    return list((await db.scalars(stmt)).all())


async def get(db: AsyncSession, feature_id: uuid.UUID) -> FeatureRequest | None:
    return await db.get(FeatureRequest, feature_id)


async def load_attribution(
    db: AsyncSession, feature_id: uuid.UUID
) -> list[tuple[str, str | None, str | None]]:
    """Return ``(company_name, user_email, details)`` for each vote on a request."""
    rows = (
        await db.execute(
            select(Company.name, User.email, FeatureRequestVote.details)
            .select_from(FeatureRequestVote)
            .join(Company, Company.id == FeatureRequestVote.company_id)
            .outerjoin(User, User.id == FeatureRequestVote.user_id)
            .where(FeatureRequestVote.feature_request_id == feature_id)
            .order_by(FeatureRequestVote.created_at.asc())
        )
    ).all()
    return [(name, email, details) for name, email, details in rows]


async def requesting_company_ids(
    db: AsyncSession, feature_id: uuid.UUID
) -> list[uuid.UUID]:
    """Distinct company ids that voted for a request — the delivery-notice targets."""
    rows = await db.scalars(
        select(FeatureRequestVote.company_id)
        .where(FeatureRequestVote.feature_request_id == feature_id)
        .distinct()
    )
    return list(rows)


async def build_issue_body(db: AsyncSession, fr: FeatureRequest) -> str:
    """Compose a tracker-issue body summarizing demand + who asked + their framing."""
    attribution = await load_attribution(db, fr.id)
    companies = sorted({name for name, _email, _d in attribution})
    users = sorted({email for _n, email, _d in attribution if email})

    lines = [
        fr.details.strip(),
        "",
        "---",
        f"**Demand:** {fr.vote_count} vote(s) — "
        f"{len(companies)} compan{'y' if len(companies) == 1 else 'ies'}, "
        f"{len(users)} named user(s).",
    ]
    if companies:
        lines.append("**Companies:** " + ", ".join(companies))
    if users:
        lines.append("**Users:** " + ", ".join(users))

    extra_framings = [d.strip() for _n, _e, d in attribution if d and d.strip() != fr.details.strip()]
    if extra_framings:
        lines.append("")
        lines.append("**Additional context from requesters:**")
        lines.extend(f"- {f}" for f in dict.fromkeys(extra_framings))  # dedup, keep order

    lines.append("")
    lines.append(f"_Filed from the abos feature-request backlog (entry `{fr.id}`)._")
    return "\n".join(lines)


async def mark_promoted(
    db: AsyncSession,
    fr: FeatureRequest,
    *,
    issue_number: int | None,
    issue_url: str | None,
) -> None:
    """Flag a backlog entry as filed and record the resulting tracker issue."""
    fr.status = FeatureRequestStatus.promoted
    fr.github_issue_number = issue_number
    fr.github_issue_url = issue_url
    await db.flush()


async def list_promoted(
    db: AsyncSession, *, limit: int = 50
) -> list[FeatureRequest]:
    """Promoted-but-not-yet-delivered entries that carry a tracker issue number.

    These are what the reconciler polls: each has a real issue whose closure means
    the fix shipped. Oldest-first so long-waiting asks are reconciled first.
    """
    stmt = (
        select(FeatureRequest)
        .where(
            FeatureRequest.status == FeatureRequestStatus.promoted,
            FeatureRequest.github_issue_number.is_not(None),
        )
        .order_by(FeatureRequest.created_at.asc())
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def mark_delivered(db: AsyncSession, fr: FeatureRequest) -> None:
    """Flag a promoted entry as delivered (its tracker issue closed / fix merged)."""
    fr.status = FeatureRequestStatus.delivered
    await db.flush()


__all__ = [
    "RequestOutcome",
    "coerce_kind",
    "record_request",
    "list_open",
    "get",
    "load_attribution",
    "build_issue_body",
    "mark_promoted",
    "list_promoted",
    "mark_delivered",
    "requesting_company_ids",
]
