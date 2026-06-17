"""Agent runs and tasks — the execution tree used for loop control.

``parent_task_id`` + ``depth`` + ``root_run_id`` bound recursion;
``loop_signature`` = hash(agent + normalised goal) feeds the loop breaker.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import RunStatus, RunTrigger, TaskStatus


class AgentRun(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "agent_runs"

    root_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    trigger: Mapped[RunTrigger] = mapped_column(
        Enum(RunTrigger, native_enum=False, length=20), nullable=False
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, native_enum=False, length=20), default=RunStatus.running, nullable=False
    )
    total_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Task(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "tasks"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    root_run_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Ephemeral working memory: the agent loop's in-flight conversation,
    # checkpointed after every step so a task resumes where it left off after a
    # restart instead of re-running from scratch. Cleared to NULL when the task
    # reaches a terminal state, so this column only ever holds live tasks' turns
    # and does not accumulate a permanent message log.
    transcript: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, length=20), default=TaskStatus.queued, nullable=False
    )
    cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    loop_signature: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
