"""Skill-usage telemetry — which skill each task loaded.

A durable, per-task row written when an agent calls ``load_skill``. A completed
task drops its transcript at its terminal state (see :class:`app.models.run.Task`),
so without this row there is no lasting way to attribute a task's outcome to the
skill it used. The skill optimizer joins these rows back to task outcomes
(:mod:`app.services.skill_signal`) to learn which playbooks help and which regress,
and to pick which skill to try to improve next.

Kept deliberately thin — one row per ``load_skill`` call — and written best-effort
in a SAVEPOINT, so this telemetry can never break the tool call it rides on.

Tenant-scoped and RLS-protected like every other business table.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin


class SkillUsage(Base, PKMixin, TenantMixin, TimestampMixin):
    """One row per ``load_skill`` call: which task/agent pulled which skill."""

    __tablename__ = "skill_usages"

    # SET NULL (not CASCADE): the outcome signal for a skill should survive the
    # task/agent being pruned — the skill_name + timestamp still count as a usage.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The skill's stable slug (``Skill.name``). A plain string so the library can
    #: add or rename skills without a schema change.
    skill_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
