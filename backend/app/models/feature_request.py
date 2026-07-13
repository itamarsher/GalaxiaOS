"""Internal feature-request backlog — the cross-company demand ledger.

When any agent or founder hits a gap, ``request_capability`` / ``report_bug`` no
longer wake the Platform agent to file a tracker issue directly. Instead the
request is recorded here, deduplicated by a normalized key, so the same ask from
many companies/users collapses into one entry whose vote count is the running
demand signal. A gated "promoter" agent in the abos company later reads this
backlog and files the real tracker issue (which triggers the code-resolution
workflow), keeping GitHub-side dedup/voting intact on top of this ledger.

:class:`FeatureRequest` is deliberately **global** (no ``company_id`` tenant
boundary): it aggregates demand across every tenant company, which is the whole
point of a shared backlog. Attribution of *who* asked lives in
:class:`FeatureRequestVote`, one row per (request, company, user, agent) so we can
see exactly which companies, founders, and **agents** want each thing — and so a
delivered capability can be propagated back to the agent that asked for it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PKMixin, TimestampMixin
from app.models.enums import FeatureRequestKind, FeatureRequestStatus


class FeatureRequest(Base, PKMixin, TimestampMixin):
    """A single deduplicated capability/bug ask, with its running demand tally."""

    __tablename__ = "feature_requests"

    kind: Mapped[FeatureRequestKind] = mapped_column(
        SAEnum(FeatureRequestKind, native_enum=False, length=20), nullable=False, index=True
    )
    #: Human-readable title (the first requester's wording).
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    #: Normalized dedup key (``kind:lowercased-collapsed-title``), unique so repeat
    #: asks land on the same row instead of stacking duplicates.
    dedup_key: Mapped[str] = mapped_column(String(560), nullable=False, unique=True, index=True)
    #: Representative details (the first requester's framing); per-voter framing
    #: lives on each vote.
    details: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[FeatureRequestStatus] = mapped_column(
        SAEnum(FeatureRequestStatus, native_enum=False, length=20),
        default=FeatureRequestStatus.open,
        nullable=False,
        index=True,
    )
    #: Denormalized vote count (== number of vote rows) for cheap ordering.
    vote_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    #: Set once the abos promoter files it as a real tracker issue.
    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_issue_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    votes: Mapped[list["FeatureRequestVote"]] = relationship(
        back_populates="feature_request",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class FeatureRequestVote(Base, PKMixin, TimestampMixin):
    """One (company, user, agent)'s demand for a feature request (the unit of voting).

    ``user_id`` and ``agent_id`` are both nullable and mutually exclusive in
    practice: a founder/copilot ask carries the ``user_id``; an agent-initiated ask
    carries the ``agent_id`` (and the originating ``task_id``) instead. Tracking the
    agent lets the platform see *which agent* hit the gap, and lets a delivered
    capability be routed back to that agent. A repeat ask from the same
    (company, user, agent) updates this row rather than adding another, so the count
    is honest demand, not spam.
    """

    __tablename__ = "feature_request_votes"
    __table_args__ = (
        UniqueConstraint(
            "feature_request_id",
            "company_id",
            "user_id",
            "agent_id",
            name="uq_feature_request_vote",
        ),
    )

    feature_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("feature_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The requesting tenant company. Not a TenantMixin boundary (this is a global
    #: ledger), but RLS-friendly: scoped reads see their own votes, the unscoped
    #: promoter session sees all.
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The requesting user, when known (founder/copilot path); NULL for an
    #: agent/system-initiated request.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The requesting agent, when the ask came from the runtime (an agent hit a gap
    #: via ``request_capability``/``report_bug``); NULL for a founder/copilot ask.
    #: This is how the platform sees *which agent* asked, and how a delivery notice
    #: is routed back to it.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The task the agent was running when it asked — kept so a delivery notice can
    #: point back at the work that was blocked. NULL for a founder/copilot ask.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: This voter's own framing of the ask (why they need it).
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    feature_request: Mapped[FeatureRequest] = relationship(back_populates="votes")
