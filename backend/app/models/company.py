"""Company — the aggregate root. Everything else hangs off ``company_id``."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin
from app.models.enums import CompanyStatus


class Company(Base, PKMixin, TimestampMixin):
    __tablename__ = "companies"
    __table_args__ = (
        # At most one platform (dogfooding) company: a partial-unique index over the
        # ``true`` rows lets every other company keep ``false`` while making a second
        # platform company a hard error. Kept in sync with migration 0026.
        Index(
            "uq_one_platform_company",
            "is_platform",
            unique=True,
            postgresql_where=text("is_platform"),
        ),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[CompanyStatus] = mapped_column(
        Enum(CompanyStatus, native_enum=False, length=20),
        default=CompanyStatus.draft,
        nullable=False,
    )
    # mission_id is denormalised for convenience; the authoritative link is Mission.company_id.
    mission_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # Sender ("From:") address agents send mail as, e.g. ``Acme <hello@acme.com>``.
    # Set by the founder in the UI; for Resend it must be on a domain verified in
    # their Resend account. When unset, the email sender falls back to the global
    # ``ABOS_EMAIL_FROM``.
    email_from: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # The single "platform" (dogfooding) company that operates GalaxiaOS on itself.
    # Exactly one company carries this flag (enforced by a partial-unique index), and
    # it is the ONLY tenant authorized to promote the shared feature-request backlog
    # into tracker issues (see runtime/tools/platform.py) and to use the deployment's
    # global Render key (see runtime/tools/render_ops.py). It replaces the old fixed
    # founder-user gate: the flag lives on the company, so it survives an ownership
    # transfer. Designated automatically on the first company onboarded in a
    # deployment (services/platform_company.py).
    is_platform: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The company's global operating playbook — a system prompt injected into EVERY
    # agent's launch prompt so the whole fleet shares the same best practices and
    # company-specific directives. The CEO keeps it current (``update_company_playbook``)
    # as emerging directives arise. When unset, the platform default
    # (``prompts.DEFAULT_COMPANY_PLAYBOOK``) applies, so a company always has one.
    playbook: Mapped[str | None] = mapped_column(Text, nullable=True)
