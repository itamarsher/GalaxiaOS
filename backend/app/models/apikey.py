"""BYOK provider keys — stored envelope-encrypted. Plaintext is never persisted."""

from __future__ import annotations

from sqlalchemy import Enum, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import ApiKeyStatus


class ApiKey(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "api_keys"

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    # AES-GCM ciphertext of the provider key, encrypted under the per-record data key.
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # The per-record data key (DEK), itself wrapped by the app master key.
    encrypted_data_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Display-only fingerprint (e.g. "sk-…a1b2") so the UI never needs plaintext.
    key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ApiKeyStatus] = mapped_column(
        Enum(ApiKeyStatus, native_enum=False, length=20),
        default=ApiKeyStatus.active,
        nullable=False,
    )
