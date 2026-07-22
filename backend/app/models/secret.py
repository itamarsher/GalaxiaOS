"""Generic company secrets — API keys, passwords, tokens — stored envelope-encrypted.

Same envelope scheme as :class:`~app.models.apikey.ApiKey` (a per-record data key
wrapped under the app master key), but general-purpose: any agent can *request* a
named secret and the founder fulfils it, or the founder stores one directly. The
plaintext is sealed on the way in and only ever decrypted transiently inside the
secret **broker** (:mod:`app.services.secrets`) at the outbound-HTTP boundary — it
is never returned to an agent, written to a transcript, or surfaced by the API,
which exposes the fingerprint only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import SecretStatus


class Secret(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "secrets"

    # The logical handle agents reference as ``{{secret:name}}``. Unique among the
    # company's active secrets (enforced at the service layer on store).
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    # Human-facing note on what the secret is for (never the value).
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AES-GCM ciphertext of the secret value, encrypted under the per-record data key.
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # The per-record data key (DEK), itself wrapped by the app master key.
    encrypted_data_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Display-only fingerprint (e.g. "sk-…a1b2") so the UI never needs plaintext.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Host the broker may substitute this secret into (defence in depth: a leaked
    # placeholder can't exfiltrate the value to an arbitrary domain). ``None`` = any.
    allowed_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[SecretStatus] = mapped_column(
        Enum(SecretStatus, native_enum=False, length=20),
        default=SecretStatus.active,
        nullable=False,
    )
    # The agent that requested it (``None`` when the founder stored it directly).
    requested_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
