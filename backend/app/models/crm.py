"""Self-coded CRM — the company's own system of record for relationships.

Three tenant-scoped tables back a real, persistent CRM so the sales/growth agents
have an actual store to read and write instead of fabricating pipeline:

- :class:`CrmContact` — a person or account the company is selling to or working with.
- :class:`CrmDeal` — an opportunity moving through the pipeline, optionally tied to a contact.
- :class:`CrmActivity` — a logged interaction (note/call/email/meeting) or a planned
  touchpoint (task/follow-up), optionally tied to a contact and/or deal.

Nothing here is simulated: rows persist, so reading them back is reading reality.
All access goes through :mod:`app.services.crm`, which scopes every query to the
caller's ``company_id`` (the tenant boundary, doubly enforced by RLS).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import CrmActivityKind, CrmContactStatus, CrmDealStage


class CrmContact(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "crm_contacts"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # The contact's own organisation (distinct from the tenant Company).
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[CrmContactStatus] = mapped_column(
        Enum(CrmContactStatus, native_enum=False, length=20),
        default=CrmContactStatus.lead,
        nullable=False,
        index=True,
    )
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-form custom fields / tags.
    structured: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CrmDeal(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "crm_deals"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("crm_contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    stage: Mapped[CrmDealStage] = mapped_column(
        Enum(CrmDealStage, native_enum=False, length=20),
        default=CrmDealStage.new,
        nullable=False,
        index=True,
    )
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set when the deal reaches a terminal stage (won/lost).
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CrmActivity(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "crm_activities"

    kind: Mapped[CrmActivityKind] = mapped_column(
        Enum(CrmActivityKind, native_enum=False, length=20),
        default=CrmActivityKind.note,
        nullable=False,
        index=True,
    )
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("crm_contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("crm_deals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # For planned touchpoints (task/follow-up): when it is due and whether it's done.
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
