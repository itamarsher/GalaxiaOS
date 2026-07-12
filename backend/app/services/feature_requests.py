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

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Company, FeatureRequest, FeatureRequestVote, User
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
    agent_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
) -> RequestOutcome | None:
    """Record a capability/bug request, deduped by title and voted per company/user/agent.

    Founder/copilot asks carry ``user_id``; agent asks carry ``agent_id`` (and the
    originating ``task_id``) so the platform can see which agent hit the gap and a
    delivery can be routed back to it. Returns ``None`` if the kind is unknown or the
    title is empty. A repeat ask from the same (company, user, agent) refreshes that
    vote's details/task instead of adding another vote, so ``vote_count`` is honest
    demand.
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

    # One vote per (request, company, user, agent). A founder ask keys on the user
    # (agent NULL); an agent ask keys on the agent (user NULL) — so two distinct
    # agents in one company each register demand, and a founder + an agent asking
    # the same thing are counted separately. Both NULLs match via IS NULL below.
    existing_vote = await db.scalar(
        select(FeatureRequestVote).where(
            FeatureRequestVote.feature_request_id == fr.id,
            FeatureRequestVote.company_id == company_id,
            FeatureRequestVote.user_id == user_id,
            FeatureRequestVote.agent_id == agent_id,
        )
    )
    is_new_vote = existing_vote is None
    if existing_vote is None:
        db.add(
            FeatureRequestVote(
                feature_request_id=fr.id,
                company_id=company_id,
                user_id=user_id,
                agent_id=agent_id,
                task_id=task_id,
                details=details or None,
            )
        )
        fr.vote_count = (fr.vote_count or 0) + 1
    else:
        # Refresh the originating task (point delivery at the latest blocked work)
        # and the framing on a repeat ask.
        if task_id is not None:
            existing_vote.task_id = task_id
        if details:
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


@dataclass(frozen=True)
class Attribution:
    """Who asked for a request: a company plus the requesting user *or* agent."""

    company_id: uuid.UUID
    company_name: str
    user_email: str | None
    agent_id: uuid.UUID | None
    agent_name: str | None
    details: str | None


async def load_attribution(db: AsyncSession, feature_id: uuid.UUID) -> list[Attribution]:
    """Return an :class:`Attribution` for each vote on a request (oldest first)."""
    rows = (
        await db.execute(
            select(
                FeatureRequestVote.company_id,
                Company.name,
                User.email,
                FeatureRequestVote.agent_id,
                Agent.name,
                FeatureRequestVote.details,
            )
            .select_from(FeatureRequestVote)
            .join(Company, Company.id == FeatureRequestVote.company_id)
            .outerjoin(User, User.id == FeatureRequestVote.user_id)
            .outerjoin(Agent, Agent.id == FeatureRequestVote.agent_id)
            .where(FeatureRequestVote.feature_request_id == feature_id)
            .order_by(FeatureRequestVote.created_at.asc())
        )
    ).all()
    return [
        Attribution(
            company_id=cid,
            company_name=cname,
            user_email=email,
            agent_id=aid,
            agent_name=aname,
            details=details,
        )
        for cid, cname, email, aid, aname, details in rows
    ]


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


async def requesting_agents(
    db: AsyncSession, feature_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID, str]]:
    """``(company_id, agent_id, agent_name)`` for each agent that asked.

    The delivery-routing targets: an agent-initiated vote carries the agent, so a
    'your capability shipped' notice can name the agent that hit the gap. Founder
    votes (no ``agent_id``) are excluded.
    """
    rows = (
        await db.execute(
            select(FeatureRequestVote.company_id, Agent.id, Agent.name)
            .select_from(FeatureRequestVote)
            .join(Agent, Agent.id == FeatureRequestVote.agent_id)
            .where(FeatureRequestVote.feature_request_id == feature_id)
            .order_by(FeatureRequestVote.created_at.asc())
        )
    ).all()
    return [(cid, aid, aname) for cid, aid, aname in rows]


async def build_issue_body(db: AsyncSession, fr: FeatureRequest) -> str:
    """Compose a tracker-issue body summarizing demand + who asked + their framing."""
    attribution = await load_attribution(db, fr.id)
    companies = sorted({a.company_name for a in attribution})
    users = sorted({a.user_email for a in attribution if a.user_email})
    agents = sorted({a.agent_name for a in attribution if a.agent_name})

    lines = [
        fr.details.strip(),
        "",
        "---",
        f"**Demand:** {fr.vote_count} vote(s) — "
        f"{len(companies)} compan{'y' if len(companies) == 1 else 'ies'}, "
        f"{len(users)} named user(s), {len(agents)} agent(s).",
    ]
    if companies:
        lines.append("**Companies:** " + ", ".join(companies))
    if users:
        lines.append("**Users:** " + ", ".join(users))
    if agents:
        lines.append("**Agents:** " + ", ".join(agents))

    extra_framings = [
        a.details.strip()
        for a in attribution
        if a.details and a.details.strip() != fr.details.strip()
    ]
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
    """Flag an entry as delivered (its tracker issue closed / platform marked ready)."""
    fr.status = FeatureRequestStatus.delivered
    await db.flush()


@dataclass(frozen=True)
class CompanyRequest:
    """A backlog entry as seen by a requesting company — for the founder's view.

    Bundles the shared entry (title/kind/status/issue link/total demand) with *this
    company's* own attribution rows (which of its agents/founders asked and why), so
    a founder can see every capability their company requested and whether the
    platform has delivered it.
    """

    feature_request: FeatureRequest
    attributions: list[Attribution]


async def list_for_company(
    db: AsyncSession, *, company_id: uuid.UUID, limit: int = 100
) -> list[CompanyRequest]:
    """Every backlog entry this company requested, newest-requested first.

    Scoped to the founder's own company: it lists the capabilities/bugs the
    company's agents and founders asked for, each carrying its lifecycle status
    (open → promoted → delivered) so the founder can audit what was requested and
    what the platform has since delivered.
    """
    vote_rows = (
        await db.execute(
            select(FeatureRequestVote.feature_request_id)
            .where(FeatureRequestVote.company_id == company_id)
            .group_by(FeatureRequestVote.feature_request_id)
            .order_by(sa_func.max(FeatureRequestVote.created_at).desc())
            .limit(limit)
        )
    ).all()
    out: list[CompanyRequest] = []
    for (fr_id,) in vote_rows:
        fr = await db.get(FeatureRequest, fr_id)
        if fr is None:
            continue
        attributions = [
            a for a in await load_attribution(db, fr_id) if a.company_id == company_id
        ]
        out.append(CompanyRequest(feature_request=fr, attributions=attributions))
    return out


__all__ = [
    "RequestOutcome",
    "Attribution",
    "CompanyRequest",
    "coerce_kind",
    "record_request",
    "list_open",
    "list_for_company",
    "get",
    "load_attribution",
    "build_issue_body",
    "mark_promoted",
    "list_promoted",
    "mark_delivered",
    "requesting_company_ids",
    "requesting_agents",
]
