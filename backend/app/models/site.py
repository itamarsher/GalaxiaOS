"""Sites — generated landing pages and the bought domains connected to them.

Two tenant-scoped tables back the "build a page → host it → point a domain at it"
pipeline (the marketing/growth agents previously had nowhere to publish to):

- :class:`Site` — a generated page (title + body markdown + rendered HTML) hosted
  on an external static host (e.g. Cloudflare Pages), with its live ``*.pages.dev``
  URL once published.
- :class:`SiteDomain` — a bought domain being connected to a :class:`Site`, plus the
  DNS-zone / nameserver bookkeeping needed to drive the connection state machine
  (see :class:`~app.models.enums.SiteConnectStatus`).

Nothing here is simulated: rows persist, so reading them back is reading reality.
All access goes through :mod:`app.services.sites`, which scopes every query to the
caller's ``company_id`` (the tenant boundary, doubly enforced by RLS).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import SiteConnectStatus, SiteStatus


class Site(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "sites"

    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Body markdown the agent authored, plus the HTML actually deployed.
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    html: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SiteStatus] = mapped_column(
        Enum(SiteStatus, native_enum=False, length=20),
        default=SiteStatus.draft,
        nullable=False,
        index=True,
    )
    # Which host the page lives on, the deterministic project name, and the live URL.
    provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deployment_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SiteDomain(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "site_domains"

    # The site this domain points at (SET NULL so deleting a draft doesn't orphan
    # an in-flight domain connection).
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True
    )
    domain: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # DNS bookkeeping for the connection state machine.
    zone_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    nameservers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[SiteConnectStatus] = mapped_column(
        Enum(SiteConnectStatus, native_enum=False, length=20),
        default=SiteConnectStatus.pending_ns,
        nullable=False,
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
