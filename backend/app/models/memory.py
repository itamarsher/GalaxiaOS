"""Company Memory — the institutional brain (relational + pgvector)."""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import MemoryType

EMBEDDING_DIM = 1536


class MemoryEntry(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "memory_entries"

    type: Mapped[MemoryType] = mapped_column(
        Enum(MemoryType, native_enum=False, length=30), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    structured: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Data-segmentation labels (DataLabel keys) classifying this memory. The recall
    # path withholds an entry from any agent not cleared for its labels (RFC 0001).
    # Empty/NULL = general (recalled for everyone).
    labels: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    # Nullable: embeddings are optional (vector search degrades to recency/keyword if absent).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
