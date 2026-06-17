"""Multiple businesses per account: listing a user's companies."""

from __future__ import annotations

import uuid

from app.api.companies import list_my_companies
from app.models import Company, Membership, User
from app.models.enums import CompanyStatus, MembershipRole
from tests.conftest import requires_db


@requires_db
async def test_list_my_companies_returns_all_user_memberships(session_factory):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        other = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add_all([user, other])
        await db.flush()

        for name in ("Alpha", "Beta"):
            c = Company(owner_user_id=user.id, name=name, status=CompanyStatus.active)
            db.add(c)
            await db.flush()
            db.add(Membership(user_id=user.id, company_id=c.id, role=MembershipRole.founder))
        # A company belonging to a different user must NOT appear.
        c3 = Company(owner_user_id=other.id, name="NotMine", status=CompanyStatus.active)
        db.add(c3)
        await db.flush()
        db.add(Membership(user_id=other.id, company_id=c3.id, role=MembershipRole.founder))
        await db.commit()

        rows = await list_my_companies(db, user)

    assert {c.name for c in rows} == {"Alpha", "Beta"}
