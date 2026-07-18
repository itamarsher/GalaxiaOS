"""Data segmentation labels — the company's data-classification taxonomy.

Every piece of company info can be tagged with one or more labels (financial,
customer data, private user data, …). Before data is handed to any principal that
is NOT the founder or the CEO agent, the data policy enforces that the principal is
permitted every label on that data (see ``services/data_policy.py``).

The taxonomy is **per company and founder-editable**: seeded with sensible defaults
(``is_default``), but the founder can rename, remove, or add labels, and it may grow
to dozens/hundreds. ``key`` is the stable handle referenced by principals' allowed
lists; ``name`` is the human label.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin


class DataLabel(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "data_labels"
    __table_args__ = (
        UniqueConstraint("company_id", "key", name="uq_data_label_company_key"),
    )

    # Stable slug the principals' allowed-label lists reference.
    key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Seeded default vs founder-created. Defaults are still editable/removable.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
