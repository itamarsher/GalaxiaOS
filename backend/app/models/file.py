"""Company file index — a durable record of every file in the external store.

Files themselves live in the company's :class:`~app.integrations.files.FileProvider`
(Google Drive today), but a row here is written for each one so the platform has a
tenant-scoped, queryable manifest of what exists, where, and why — independent of
the external store being reachable. That manifest is what makes the store
*auditable*: the data room, the financial trail, and the brand/knowledge library
can all be listed and reconciled from the database even if Drive is momentarily
down or a file was moved.

Tenant-scoped like every business table (``company_id`` + RLS); all access goes
through :mod:`app.services.files`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import FileCategory


class CompanyFile(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "company_files"

    category: Mapped[FileCategory] = mapped_column(
        Enum(FileCategory, native_enum=False, length=20), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    # Human-readable path within the store, e.g. ".abos/Acme/Financials".
    folder_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # Which provider holds it + its opaque id + a link a human can open.
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    web_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The task that produced/filed it (SET NULL so pruning tasks keeps the record).
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
