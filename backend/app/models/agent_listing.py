"""Agent marketplace catalog — GLOBAL (not tenant-scoped) hireable agents.

An :class:`AgentListing` is a published, company-agnostic offer in the shared
marketplace catalog. Hiring one materialises a tenant-scoped :class:`~app.models.agent.Agent`
(``source=hired``, ``backend_type=marketplace``) inside the buyer's company; the
listing itself is never tenant-scoped, hence PKMixin+TimestampMixin only.
"""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class AgentListing(Base, PKMixin, TimestampMixin):
    __tablename__ = "agent_listings"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # Published reputation (optional) — same dimensions as ReputationScore so the
    # catalog can be ranked by the same signals an in-house agent accrues.
    trust: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi: Mapped[float | None] = mapped_column(Float, nullable=True)
    reliability: Mapped[float | None] = mapped_column(Float, nullable=True)
