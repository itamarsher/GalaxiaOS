"""Per-person involvement preferences — the human-binding policy (RFC 0001).

Each company member states, in their own words, how they want to be involved in
the business. That prose is what the involvement *router* (a later step) reads to
decide when to route a task or a decision to a human, and to whom — replacing the
old global autonomy scale with per-person, natural-language preferences that also
work for a *team* of humans, not just the founder.

**The founder is always in ultimate control.** Only founder-sanctioned prose ever
drives routing:

- The founder sets any member's active ``involvement`` directly (:func:`set_involvement`).
- A teammate may only *propose* their own (:func:`propose_involvement`), which lands
  in ``proposed_involvement`` and does nothing until the founder approves it
  (:func:`approve_involvement`, optionally editing it first). The router reads
  ``involvement`` only — never a pending proposal — so a teammate can't grant
  themselves broader involvement/authority.

This module is the policy store + the founder-control flows; consuming the policy
to route work is a separate step.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Membership
from app.models.enums import MembershipRole


class InvolvementError(Exception):
    """A founder-control invariant was violated (e.g. no pending proposal)."""


async def _membership(
    db: AsyncSession, *, company_id: uuid.UUID, user_id: uuid.UUID
) -> Membership:
    m = await db.scalar(
        select(Membership).where(
            Membership.company_id == company_id, Membership.user_id == user_id
        )
    )
    if m is None:
        raise InvolvementError("not a member of this company")
    return m


async def is_founder(
    db: AsyncSession, *, company_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """Whether ``user_id`` holds the founder role in ``company_id``."""
    m = await db.scalar(
        select(Membership).where(
            Membership.company_id == company_id, Membership.user_id == user_id
        )
    )
    return m is not None and m.role is MembershipRole.founder


async def set_involvement(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    text: str,
    coverage: str | None = None,
) -> Membership:
    """Set a member's ACTIVE (sanctioned) involvement. A founder-authorised write.

    Clears any pending proposal, since the founder has just spoken directly. The
    caller is responsible for confirming the actor is the founder (for another
    member) — this is the sanctioned-write primitive.
    """
    m = await _membership(db, company_id=company_id, user_id=user_id)
    m.involvement = text.strip() or None
    if coverage is not None:
        m.coverage = coverage.strip() or None
    m.proposed_involvement = None
    await db.flush()
    return m


async def propose_involvement(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    text: str,
) -> Membership:
    """A teammate proposes their OWN involvement. Inert until the founder approves.

    Stored in ``proposed_involvement``; the router never reads it, so proposing
    grants nothing on its own.
    """
    m = await _membership(db, company_id=company_id, user_id=user_id)
    m.proposed_involvement = text.strip() or None
    await db.flush()
    return m


async def approve_involvement(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    edited_text: str | None = None,
) -> Membership:
    """Founder approves a member's pending proposal (optionally editing it first).

    Promotes ``proposed_involvement`` (or ``edited_text`` if the founder revised it)
    to the active ``involvement`` and clears the proposal. Raises if there is nothing
    to approve and no explicit text is supplied. Founder authorisation is the
    caller's responsibility.
    """
    m = await _membership(db, company_id=company_id, user_id=user_id)
    text = (edited_text if edited_text is not None else m.proposed_involvement) or ""
    text = text.strip()
    if not text:
        raise InvolvementError("no pending involvement proposal to approve")
    m.involvement = text
    m.proposed_involvement = None
    await db.flush()
    return m


async def team_involvement(
    db: AsyncSession, *, company_id: uuid.UUID
) -> list[Membership]:
    """Every member's membership (with active involvement) — the router's input."""
    rows = await db.scalars(
        select(Membership).where(Membership.company_id == company_id)
    )
    return list(rows)
