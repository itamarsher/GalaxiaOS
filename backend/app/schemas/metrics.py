"""Metrics API DTOs: founder/integration outcome signals in and out."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas import ORMModel


class MetricSignalIn(BaseModel):
    name: str = Field(min_length=1)
    value: float
    unit: str | None = None
    note: str | None = None


class MetricSignalOut(ORMModel):
    id: uuid.UUID
    name: str
    value: float
    unit: str | None = None
    note: str | None = None
    source: str
    captured_at: datetime
