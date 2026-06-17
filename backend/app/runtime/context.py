"""Shared runtime context passed to backends and the agent loop."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.providers.base import LLMProvider
from app.runtime.cost_meter import CostMeter


@dataclass
class RuntimeContext:
    session_factory: async_sessionmaker[AsyncSession]
    cost_meter: CostMeter
    provider: LLMProvider
    enqueue_task: callable  # async (task_id, *, delay_seconds=0) -> None  (arq enqueue)
