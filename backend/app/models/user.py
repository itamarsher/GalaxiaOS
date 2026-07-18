"""Users and company memberships (the who-can-access mapping)."""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin
from app.models.enums import MembershipRole


class User(Base, PKMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    # Nullable: an account created via Google SSO has no local password. A
    # password-based account still sets this; the two paths coexist (SSO is the
    # default button, email/password remains a fallback).
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Google account identity. ``google_sub`` is Google's stable, immutable subject
    # id for the account — the canonical join key for SSO login (email can change).
    # ``name`` is the display name from the userinfo endpoint.
    google_sub: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Account-wide Google Drive: a personal file store connected ONCE per user (not
    # per company), so every business the user launches files into the same Drive.
    # The refresh token is envelope-encrypted exactly like a BYOK key (ciphertext +
    # wrapped data key + nonce); only these three blobs are stored, never plaintext.
    # ``gdrive_root_folder_id`` names the Drive folder documents are filed under.
    gdrive_refresh_ct: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    gdrive_refresh_dek: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    gdrive_refresh_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    gdrive_root_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Membership(Base, PKMixin, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_membership_user_company"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, native_enum=False, length=20),
        default=MembershipRole.founder,
        nullable=False,
    )
    # How this person wants to be involved in the business, in their own words —
    # the input the involvement router reads to decide when to route a task or a
    # decision to a human, and to whom (RFC 0001, human binding). Replaces the old
    # global autonomy scale with per-person, natural-language preferences.
    #
    # ``involvement`` is the ACTIVE, founder-sanctioned prose — the ONLY field the
    # router ever reads. A teammate cannot self-escalate: they may submit
    # ``proposed_involvement`` (a pending proposal), which the founder must approve
    # (or the founder writes ``involvement`` directly). The founder stays in
    # ultimate control. NULL involvement = no stated human involvement.
    involvement: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_involvement: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional area/function focus, a prior for routing (e.g. "finance, fundraising").
    coverage: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Data-segmentation policy: the ``DataLabel.key``s this human may be given. The
    # founder sets it when onboarding the person. The founder bypasses this (full
    # access); every other human is filtered to data whose labels are all in this
    # list. NULL/empty => only unlabelled data. RFC 0001.
    access_labels: Mapped[list | None] = mapped_column(JSONB, nullable=True)
