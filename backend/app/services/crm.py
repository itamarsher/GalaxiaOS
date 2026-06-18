"""CRM service — the persistence and query logic behind the self-coded CRM.

Every function is tenant-scoped: callers pass the ``company_id`` resolved from
the auth/runtime context and queries never cross that boundary (RLS is the second
line of defence). Tools in :mod:`app.runtime.tools.crm` are thin wrappers over
these functions; keeping the logic here means the same behaviour is reachable
from tools, the API, and tests without duplication.

Resolution helpers (:func:`resolve_contact`, :func:`resolve_deal`) let agents
refer to records by a human handle — a name, email, or deal title — instead of a
UUID, while still accepting a UUID when they have one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CrmActivity, CrmContact, CrmDeal
from app.models.enums import CrmActivityKind, CrmContactStatus, CrmDealStage

#: Deal stages that close a deal (and stamp ``closed_at``).
TERMINAL_STAGES: frozenset[CrmDealStage] = frozenset({CrmDealStage.won, CrmDealStage.lost})


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Best-effort parse of a UUID; ``None`` when the value isn't one."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


# ─────────────────────────────── contacts ───────────────────────────────


async def resolve_contact(
    db: AsyncSession, *, company_id: uuid.UUID, handle: str | uuid.UUID
) -> CrmContact | None:
    """Find a contact by id, then exact email, then case-insensitive name."""
    cid = _as_uuid(handle)
    if cid is not None:
        contact = await db.scalar(
            select(CrmContact).where(CrmContact.company_id == company_id, CrmContact.id == cid)
        )
        if contact is not None:
            return contact

    handle_str = str(handle).strip()
    if not handle_str:
        return None
    return await db.scalar(
        select(CrmContact)
        .where(
            CrmContact.company_id == company_id,
            or_(
                func.lower(CrmContact.email) == handle_str.lower(),
                func.lower(CrmContact.name) == handle_str.lower(),
            ),
        )
        .order_by(CrmContact.created_at.asc())
    )


async def upsert_contact(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    company_name: str | None = None,
    title: str | None = None,
    source: str | None = None,
    status: CrmContactStatus | None = None,
    note: str | None = None,
    contact_id: str | uuid.UUID | None = None,
) -> tuple[CrmContact, bool]:
    """Create or update a contact; returns ``(contact, created)``.

    An existing contact is matched by ``contact_id`` first, then by email — so
    re-logging the same person updates one row instead of stacking duplicates.
    Only the fields actually provided are written (None means "leave as is").
    """
    existing: CrmContact | None = None
    cid = _as_uuid(contact_id)
    if cid is not None:
        existing = await db.scalar(
            select(CrmContact).where(CrmContact.company_id == company_id, CrmContact.id == cid)
        )
        if existing is None:
            raise ValueError(f"no contact with id {contact_id}")
    elif email:
        existing = await db.scalar(
            select(CrmContact).where(
                CrmContact.company_id == company_id,
                func.lower(CrmContact.email) == email.strip().lower(),
            )
        )

    if existing is None:
        if not (name or email):
            raise ValueError("a new contact needs at least a name or an email")
        contact = CrmContact(
            company_id=company_id,
            name=(name or email or "").strip()[:255],
            email=email,
            phone=phone,
            company_name=company_name,
            title=title,
            source=source,
            status=status or CrmContactStatus.lead,
            note=note,
        )
        db.add(contact)
        await db.flush()
        return contact, True

    for field, value in (
        ("name", name.strip()[:255] if name else None),
        ("email", email),
        ("phone", phone),
        ("company_name", company_name),
        ("title", title),
        ("source", source),
        ("status", status),
        ("note", note),
    ):
        if value is not None:
            setattr(existing, field, value)
    await db.flush()
    return existing, False


async def find_contacts(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    query: str | None = None,
    status: CrmContactStatus | None = None,
    limit: int = 20,
) -> list[CrmContact]:
    """Search contacts by free text (name/email/company) and/or status."""
    stmt = select(CrmContact).where(CrmContact.company_id == company_id)
    if status is not None:
        stmt = stmt.where(CrmContact.status == status)
    if query:
        like = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(CrmContact.name).like(like),
                func.lower(CrmContact.email).like(like),
                func.lower(CrmContact.company_name).like(like),
            )
        )
    stmt = stmt.order_by(CrmContact.updated_at.desc()).limit(max(1, min(limit, 100)))
    return list((await db.scalars(stmt)).all())


# ──────────────────────────────── deals ─────────────────────────────────


async def resolve_deal(
    db: AsyncSession, *, company_id: uuid.UUID, handle: str | uuid.UUID
) -> CrmDeal | None:
    """Find a deal by id, then by case-insensitive title."""
    did = _as_uuid(handle)
    if did is not None:
        deal = await db.scalar(
            select(CrmDeal).where(CrmDeal.company_id == company_id, CrmDeal.id == did)
        )
        if deal is not None:
            return deal
    handle_str = str(handle).strip()
    if not handle_str:
        return None
    return await db.scalar(
        select(CrmDeal)
        .where(
            CrmDeal.company_id == company_id,
            func.lower(CrmDeal.title) == handle_str.lower(),
        )
        .order_by(CrmDeal.created_at.desc())
    )


async def upsert_deal(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    title: str | None = None,
    stage: CrmDealStage | None = None,
    amount_cents: int | None = None,
    note: str | None = None,
    contact_id: str | uuid.UUID | None = None,
    deal_id: str | uuid.UUID | None = None,
) -> tuple[CrmDeal, bool]:
    """Create a deal or advance an existing one; returns ``(deal, created)``.

    An existing deal is matched by ``deal_id`` first, then by exact title. Moving
    a deal to a terminal stage (won/lost) stamps ``closed_at``.
    """
    existing: CrmDeal | None = None
    did = _as_uuid(deal_id)
    if did is not None:
        existing = await db.scalar(
            select(CrmDeal).where(CrmDeal.company_id == company_id, CrmDeal.id == did)
        )
        if existing is None:
            raise ValueError(f"no deal with id {deal_id}")
    elif title:
        existing = await resolve_deal(db, company_id=company_id, handle=title)

    contact_uuid = _as_uuid(contact_id)

    if existing is None:
        if not title:
            raise ValueError("a new deal needs a title")
        deal = CrmDeal(
            company_id=company_id,
            title=title.strip()[:255],
            stage=stage or CrmDealStage.new,
            amount_cents=amount_cents,
            note=note,
            contact_id=contact_uuid,
        )
        if deal.stage in TERMINAL_STAGES:
            deal.closed_at = datetime.now(UTC)
        db.add(deal)
        await db.flush()
        return deal, True

    if title:
        existing.title = title.strip()[:255]
    if amount_cents is not None:
        existing.amount_cents = amount_cents
    if note is not None:
        existing.note = note
    if contact_uuid is not None:
        existing.contact_id = contact_uuid
    if stage is not None:
        existing.stage = stage
        existing.closed_at = datetime.now(UTC) if stage in TERMINAL_STAGES else None
    await db.flush()
    return existing, False


async def list_deals(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    stage: CrmDealStage | None = None,
    limit: int = 50,
) -> list[CrmDeal]:
    stmt = select(CrmDeal).where(CrmDeal.company_id == company_id)
    if stage is not None:
        stmt = stmt.where(CrmDeal.stage == stage)
    stmt = stmt.order_by(CrmDeal.updated_at.desc()).limit(max(1, min(limit, 200)))
    return list((await db.scalars(stmt)).all())


async def pipeline_summary(
    db: AsyncSession, *, company_id: uuid.UUID
) -> dict[CrmDealStage, dict[str, int]]:
    """Per-stage ``{count, value_cents}`` rollup across the whole pipeline."""
    rows = (
        await db.execute(
            select(
                CrmDeal.stage,
                func.count(CrmDeal.id),
                func.coalesce(func.sum(CrmDeal.amount_cents), 0),
            )
            .where(CrmDeal.company_id == company_id)
            .group_by(CrmDeal.stage)
        )
    ).all()
    summary = {stage: {"count": 0, "value_cents": 0} for stage in CrmDealStage}
    for stage, count, value in rows:
        summary[stage] = {"count": int(count), "value_cents": int(value)}
    return summary


# ────────────────────────────── activities ──────────────────────────────


async def log_activity(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    kind: CrmActivityKind,
    subject: str | None = None,
    body: str | None = None,
    contact_id: str | uuid.UUID | None = None,
    deal_id: str | uuid.UUID | None = None,
    due_at: datetime | None = None,
) -> CrmActivity:
    activity = CrmActivity(
        company_id=company_id,
        kind=kind,
        subject=subject[:500] if subject else None,
        body=body,
        contact_id=_as_uuid(contact_id),
        deal_id=_as_uuid(deal_id),
        due_at=due_at,
    )
    db.add(activity)
    await db.flush()
    return activity


async def list_activities(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    contact_id: str | uuid.UUID | None = None,
    deal_id: str | uuid.UUID | None = None,
    limit: int = 50,
) -> list[CrmActivity]:
    stmt = select(CrmActivity).where(CrmActivity.company_id == company_id)
    cid = _as_uuid(contact_id)
    did = _as_uuid(deal_id)
    if cid is not None:
        stmt = stmt.where(CrmActivity.contact_id == cid)
    if did is not None:
        stmt = stmt.where(CrmActivity.deal_id == did)
    stmt = stmt.order_by(CrmActivity.created_at.desc()).limit(max(1, min(limit, 200)))
    return list((await db.scalars(stmt)).all())
