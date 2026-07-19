"""Data segmentation policy — the company's data-classification + access control.

Two halves:

- **Taxonomy** — a per-company, founder-editable set of :class:`DataLabel`s, seeded
  with sensible defaults. The founder can rename, remove, or add labels; it may grow
  to dozens/hundreds.
- **Access** — every principal that is NOT the founder (human) or the CEO agent may
  only be given data whose labels are all in that principal's ``access_labels`` (set
  by the founder when hiring an agent / onboarding a human). Unlabelled data is
  general and reaches everyone; a resource tagged with *any* label the principal
  lacks is withheld.

This module owns the taxonomy + policy and the pure enforcement primitive; wiring it
into each data-access path (files, memory, the mandate, …) is a follow-up. RFC 0001.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, DataLabel, Membership
from app.models.enums import AgentRole, MembershipRole

# Hard-coded starting taxonomy. Founder-editable afterwards (all ``is_default``).
DEFAULT_LABELS: list[tuple[str, str, str]] = [
    ("financial", "Financial data", "Revenue, costs, budgets, pricing, and forecasts."),
    ("customers", "Customer & user data", "Customer/user records and usage — non-private."),
    ("customers_private", "Private user data (PII)",
     "Personally identifiable or otherwise sensitive user data."),
    ("strategy", "Strategy & roadmap", "Plans, positioning, and the roadmap."),
    ("legal", "Legal & compliance", "Contracts, ToS, policies, and compliance."),
    ("people", "Team & HR", "Team, hiring, performance, and compensation."),
    ("product", "Product & engineering", "Product specs, code, and technical detail."),
    ("marketing", "Marketing & brand", "Campaigns, brand, and content."),
]


class DataPolicyError(Exception):
    """An invalid taxonomy/policy operation (unknown label, duplicate key, …)."""


# Default classification for a stored file, by its category. Conservative: only the
# clearly-sensitive categories are labelled; the rest stay general (accessible).
# Founder/agents can re-label a file afterwards. Keys must exist in DEFAULT_LABELS.
_CATEGORY_LABELS: dict[str, list[str]] = {
    "financial": ["financial"],
    "data_room": ["legal"],
    "brand": ["marketing"],
}


def default_labels_for_category(category: str) -> list[str]:
    """The default data labels a newly-filed document in ``category`` carries."""
    return list(_CATEGORY_LABELS.get(category, []))


# Default data-access an agent gets by ROLE when the founder hasn't hand-picked it.
# Each role receives the labels its job needs; the two most sensitive labels
# (``customers_private`` PII and ``people`` HR) are NEVER granted by default — the
# founder grants those explicitly. The CEO bypasses segmentation entirely, so it
# needs none; a ``custom`` role starts empty (the founder defined it, so they
# configure its access). Keys must exist in DEFAULT_LABELS.
_ROLE_ACCESS: dict[str, list[str]] = {
    "growth": ["customers", "marketing", "strategy", "product"],
    "research": ["customers", "strategy", "product", "marketing"],
    "product": ["product", "strategy", "customers"],
    "design": ["product", "marketing", "strategy"],
    "finance": ["financial", "strategy"],
    "governance": ["legal", "strategy"],
    "auditor": ["financial", "legal", "strategy", "product", "customers"],
    "data": ["customers", "product", "strategy"],
    "platform": ["product", "strategy"],
}


def default_access_labels_for_role(role: str) -> list[str]:
    """The default data-access labels a newly-created agent of ``role`` gets.

    A sensible per-role starting policy the founder can widen or narrow afterwards
    (via ``set_agent_access``). The CEO bypasses segmentation, so its access is
    irrelevant; ``custom`` and any unknown role start with none.
    """
    return list(_ROLE_ACCESS.get(role, []))


# ── taxonomy ───────────────────────────────────────────────────────────────────
async def seed_default_labels(db: AsyncSession, company_id: uuid.UUID) -> None:
    """Insert the default taxonomy for a company that has none yet (idempotent)."""
    count = await db.scalar(
        select(func.count()).select_from(DataLabel).where(DataLabel.company_id == company_id)
    )
    if count:
        return
    for key, name, desc in DEFAULT_LABELS:
        db.add(DataLabel(company_id=company_id, key=key, name=name, description=desc,
                         is_default=True))
    await db.flush()


async def list_labels(
    db: AsyncSession, company_id: uuid.UUID, *, seed: bool = True
) -> list[DataLabel]:
    """The company's labels; seeds the defaults on first access when ``seed``."""
    stmt = select(DataLabel).where(DataLabel.company_id == company_id).order_by(DataLabel.key)
    rows = list(await db.scalars(stmt))
    if not rows and seed:
        await seed_default_labels(db, company_id)
        rows = list(await db.scalars(stmt))
    return rows


async def _label_keys(db: AsyncSession, company_id: uuid.UUID) -> set[str]:
    rows = await db.scalars(select(DataLabel.key).where(DataLabel.company_id == company_id))
    return set(rows)


async def create_label(
    db: AsyncSession, company_id: uuid.UUID, *, key: str, name: str, description: str | None = None
) -> DataLabel:
    key = key.strip().lower()
    if not key:
        raise DataPolicyError("a label needs a key")
    if key in await _label_keys(db, company_id):
        raise DataPolicyError(f"label {key!r} already exists")
    label = DataLabel(company_id=company_id, key=key, name=name.strip(),
                      description=(description or None), is_default=False)
    db.add(label)
    await db.flush()
    return label


async def _get_label(db: AsyncSession, company_id: uuid.UUID, key: str) -> DataLabel:
    label = await db.scalar(
        select(DataLabel).where(DataLabel.company_id == company_id, DataLabel.key == key)
    )
    if label is None:
        raise DataPolicyError(f"label {key!r} not found")
    return label


async def update_label(
    db: AsyncSession, company_id: uuid.UUID, key: str, *,
    name: str | None = None, description: str | None = None,
) -> DataLabel:
    label = await _get_label(db, company_id, key)
    if name is not None:
        label.name = name.strip()
    if description is not None:
        label.description = description.strip() or None
    await db.flush()
    return label


async def delete_label(db: AsyncSession, company_id: uuid.UUID, key: str) -> None:
    await db.delete(await _get_label(db, company_id, key))
    await db.flush()


# ── per-principal access policy ────────────────────────────────────────────────
async def _validate_labels(db, company_id, labels: list[str]) -> list[str]:
    keys = await _label_keys(db, company_id)
    cleaned = [str(x).strip().lower() for x in labels if str(x).strip()]
    unknown = [k for k in cleaned if k not in keys]
    if unknown:
        raise DataPolicyError(f"unknown labels: {', '.join(sorted(set(unknown)))}")
    # Preserve order, drop dupes.
    return list(dict.fromkeys(cleaned))


async def validate_labels(db: AsyncSession, company_id: uuid.UUID, labels: list[str]) -> list[str]:
    """Normalise + validate label keys against the company taxonomy (public helper)."""
    return await _validate_labels(db, company_id, labels)


async def set_agent_access(
    db: AsyncSession, company_id: uuid.UUID, agent_id: uuid.UUID, labels: list[str]
) -> Agent:
    agent = await db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    )
    if agent is None:
        raise DataPolicyError("agent not found")
    agent.access_labels = await _validate_labels(db, company_id, labels)
    await db.flush()
    return agent


async def set_member_access(
    db: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID, labels: list[str]
) -> Membership:
    m = await db.scalar(
        select(Membership).where(
            Membership.company_id == company_id, Membership.user_id == user_id
        )
    )
    if m is None:
        raise DataPolicyError("member not found")
    m.access_labels = await _validate_labels(db, company_id, labels)
    await db.flush()
    return m


# ── enforcement primitive ──────────────────────────────────────────────────────
def permits(allowed_labels: list[str] | None, resource_labels: list[str] | None) -> bool:
    """A principal permits a resource iff it holds every one of the resource's labels.

    Unlabelled resources (empty ``resource_labels``) are general and pass for anyone.
    """
    return set(resource_labels or []) <= set(allowed_labels or [])


def agent_can_access(agent: Agent, resource_labels: list[str] | None) -> bool:
    """The CEO agent bypasses segmentation; every other agent is filtered."""
    if agent.role is AgentRole.ceo:
        return True
    return permits(agent.access_labels, resource_labels)


def filter_by_access(agent: Agent, items, *, labels):
    """Keep only the items ``agent`` may access. ``labels(item) -> list[str] | None``.

    A small reusable gate for the read paths that hand an agent a *set* of stored
    records (e.g. recalled memory) — withhold anything the agent isn't cleared for
    before it reaches the model, without leaking that it existed.
    """
    return [it for it in items if agent_can_access(agent, labels(it))]


def member_can_access(membership: Membership, resource_labels: list[str] | None) -> bool:
    """The founder bypasses segmentation; every other human is filtered."""
    if membership.role is MembershipRole.founder:
        return True
    return permits(membership.access_labels, resource_labels)
