"""Managed-mode platform billing: per-founder allowance + platform-spend ledger.

These tables back the hosted "no keys needed" tier. Unlike the business
``budgets`` (which meter a *company's* own spend against the founder's chosen
budget), these track spend the *platform* funds on a founder's behalf when they
bring no key of their own — pooled per founder ACCOUNT (``user_id``), across
every company they own, so new companies can't multiply the free tier.

Deliberately **global** (keyed by ``user_id``, not ``company_id``): they cross
the tenant boundary by design and therefore carry no ``TenantMixin`` and get no
RLS policy — exactly like ``users`` and the shared ``feature_requests`` backlog.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin
from app.models.enums import ManagedTier


class PlatformBillingAccount(Base, PKMixin, TimestampMixin):
    """One row per founder: their managed tier + running platform-funded spend."""

    __tablename__ = "platform_billing_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    tier: Mapped[ManagedTier] = mapped_column(
        Enum(ManagedTier, native_enum=False, length=20),
        default=ManagedTier.free,
        nullable=False,
    )
    # Lifetime cumulative platform-funded spend, in cents. Monotonic. The free
    # allowance is exhausted once this crosses ``settings.platform_free_tier_cents``.
    platform_spent_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Stripe linkage for the paid managed tier (set when the founder upgrades).
    stripe_customer_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    stripe_subscription_item_id: Mapped[str | None] = mapped_column(String(80), nullable=True)


class PlatformCharge(Base, PKMixin, TimestampMixin):
    """Append-only ledger of every platform-funded charge (audit + billing feed)."""

    __tablename__ = "platform_charges"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The company the spend was on. Nullable so a charge survives company deletion
    # for billing/audit; SET NULL rather than CASCADE.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cents: Mapped[int] = mapped_column(Integer, nullable=False)
    # What incurred it: "llm" | "web_search" | "media" (free-form, matches the
    # capability seam) — kept as a short string, not an enum, so a new managed
    # capability doesn't require a migration.
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # Whether this charge has been reported to the paid-managed billing provider.
    # Free-tier charges stay ``False`` forever (never billed).
    billed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
