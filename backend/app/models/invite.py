"""Team invites — pending memberships consumed when the invitee authenticates.

A founder invites a teammate by email and pre-sets their data-access labels (and
role). The invite sits ``pending`` until that email registers or signs in via
Google SSO, at which point the auth path calls
:func:`app.services.invites.consume_for_user` to materialise the ``Membership``.
So a teammate joins simply by logging in with the invited address — no shared
secret, no separate accept step. Founder-controlled throughout: only the founder
creates/revokes invites, and a teammate's involvement still needs founder approval
(see :mod:`app.services.involvement`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import InviteStatus, MembershipRole


class CompanyInvite(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "company_invites"

    #: The invited address (lower-cased on write); matched against the user's email
    #: when they authenticate.
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, native_enum=False, length=20),
        default=MembershipRole.admin,
        nullable=False,
    )
    #: Data-access labels the teammate's membership is created with.
    access_labels: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[InviteStatus] = mapped_column(
        Enum(InviteStatus, native_enum=False, length=20),
        default=InviteStatus.pending,
        nullable=False,
        index=True,
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
