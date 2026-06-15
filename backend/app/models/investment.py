"""Investment review — three agentic investors weigh in at onboarding.

After the plan + org are generated, three investor personas each produce a
structured verdict on the venture: a small-business investor (cash-flow lens),
a startup/VC investor (venture-scale lens), and a devil's-advocate nay-sayer
(the bear case). Persisted so the founder can revisit them and so later cycles
can reference the original thesis and risks.
"""

from __future__ import annotations

from sqlalchemy import Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import InvestmentStance, InvestorPersona


class InvestmentReview(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "investment_reviews"

    persona: Mapped[InvestorPersona] = mapped_column(
        Enum(InvestorPersona, native_enum=False, length=30), nullable=False, index=True
    )
    stance: Mapped[InvestmentStance] = mapped_column(
        Enum(InvestmentStance, native_enum=False, length=20), nullable=False
    )
    #: Conviction 0–100 (how strongly the investor holds the stance).
    conviction: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    headline: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    thesis: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    strengths: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    risks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    conditions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
