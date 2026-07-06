"""Artifacts — founder-facing deliverables produced by agents.

A first-class, persisted report the founder reads (investor update, growth/research
report, board brief). Distinct from Company Memory (institutional learnings the
*agents* recall) and from ExternalMessage (things actually sent outside the
company): an Artifact is internal-facing synthesis the founder consumes. Agents
create one with the ``create_report`` tool; the founder can also generate one on
demand from the Reports tab.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin


class Artifact(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "artifacts"

    # Free-form category, e.g. investor_update | growth_report | research_report |
    # board_brief | custom. Kept as a string (not an enum) so agents can coin new
    # report kinds without a migration.
    kind: Mapped[str] = mapped_column(String(40), default="custom", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    # Provenance: which task/agent produced it (nullable — founder-generated ones
    # have neither).
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    source_agent_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
