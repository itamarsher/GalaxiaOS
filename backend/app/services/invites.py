"""Team invites service — create/list/revoke, and consume on authentication.

Founder-authorisation is the caller's responsibility (the API layer checks it);
this module is the store + the consume primitive the auth paths call.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyInvite, Membership, User
from app.models.enums import InviteStatus, MembershipRole
from app.services import data_policy


class InviteError(Exception):
    """An invalid invite operation (already a member, bad labels, …)."""


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


async def create_invite(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    email: str,
    labels: list[str] | None = None,
    role: MembershipRole = MembershipRole.admin,
    invited_by_user_id: uuid.UUID | None = None,
) -> CompanyInvite:
    """Invite ``email`` to the company with pre-set access labels.

    Idempotent per (company, email): re-inviting a still-pending address updates its
    labels rather than stacking duplicates. The founder can never invite another
    founder (role is clamped to non-founder)."""
    addr = _norm_email(email)
    if not addr or "@" not in addr:
        raise InviteError("a valid email is required")
    if role is MembershipRole.founder:
        raise InviteError("cannot invite another founder")
    clean_labels = await data_policy.validate_labels(db, company_id, labels or [])

    existing = await db.scalar(
        select(CompanyInvite).where(
            CompanyInvite.company_id == company_id,
            func.lower(CompanyInvite.email) == addr,
            CompanyInvite.status == InviteStatus.pending,
        )
    )
    if existing is not None:
        existing.access_labels = clean_labels
        existing.role = role
        await db.flush()
        return existing

    invite = CompanyInvite(
        company_id=company_id,
        email=addr,
        role=role,
        access_labels=clean_labels,
        status=InviteStatus.pending,
        invited_by_user_id=invited_by_user_id,
    )
    db.add(invite)
    await db.flush()
    return invite


async def list_invites(
    db: AsyncSession, *, company_id: uuid.UUID, pending_only: bool = True
) -> list[CompanyInvite]:
    stmt = select(CompanyInvite).where(CompanyInvite.company_id == company_id)
    if pending_only:
        stmt = stmt.where(CompanyInvite.status == InviteStatus.pending)
    stmt = stmt.order_by(CompanyInvite.created_at.desc())
    return list(await db.scalars(stmt))


async def revoke_invite(
    db: AsyncSession, *, company_id: uuid.UUID, invite_id: uuid.UUID
) -> None:
    invite = await db.scalar(
        select(CompanyInvite).where(
            CompanyInvite.id == invite_id, CompanyInvite.company_id == company_id
        )
    )
    if invite is None:
        raise InviteError("invite not found")
    invite.status = InviteStatus.revoked
    await db.flush()


async def consume_for_user(db: AsyncSession, user: User) -> int:
    """Materialise memberships for every pending invite matching ``user``'s email.

    Called from the auth paths (signup / password login / Google SSO upsert) so a
    teammate joins by simply authenticating with the invited address. Idempotent:
    an invite whose company the user already belongs to is just marked accepted; it
    never creates a duplicate membership. Returns how many invites were accepted."""
    addr = _norm_email(user.email)
    if not addr:
        return 0
    invites = list(
        await db.scalars(
            select(CompanyInvite).where(
                func.lower(CompanyInvite.email) == addr,
                CompanyInvite.status == InviteStatus.pending,
            )
        )
    )
    accepted = 0
    for inv in invites:
        member = await db.scalar(
            select(Membership).where(
                Membership.company_id == inv.company_id, Membership.user_id == user.id
            )
        )
        if member is None:
            db.add(
                Membership(
                    user_id=user.id,
                    company_id=inv.company_id,
                    role=inv.role,
                    access_labels=inv.access_labels,
                )
            )
        inv.status = InviteStatus.accepted
        inv.accepted_user_id = user.id
        accepted += 1
    if accepted:
        await db.flush()
    return accepted
