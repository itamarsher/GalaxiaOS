"""Tests for the involvement router (RFC 0001, human binding).

The pure prompt-build/parse helpers carry the logic (only sanctioned prose is used;
a hallucinated member is rejected); ``route`` is covered for the no-model founder
fallback and a monkeypatched-LLM happy path.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models.enums import MembershipRole
from app.services import involvement_router as ir
from tests.conftest import requires_db


def _m(user_id, role, involvement, coverage=None):
    return SimpleNamespace(user_id=user_id, role=role, involvement=involvement, coverage=coverage)


# ── pure helpers ───────────────────────────────────────────────────────────────
def test_team_block_uses_only_sanctioned_prose():
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    members = [
        _m(u1, MembershipRole.founder, "approve anything over $500", coverage="finance"),
        _m(u2, MembershipRole.admin, None),  # no sanctioned prose → skipped
    ]
    block = ir.build_team_block(members)
    assert str(u1) in block and "over $500" in block and "covers: finance" in block
    assert str(u2) not in block

    assert "no member" in ir.build_team_block([_m(uuid.uuid4(), MembershipRole.admin, None)])


def test_parse_rejects_hallucinated_member():
    real = uuid.uuid4()
    d = ir.parse_decision(
        f'{{"involve_human": true, "user_id": "{real}", "reason": "matches"}}', {real}
    )
    assert d.involve_human and d.user_id == real

    # A user_id not on the team is dropped (can't route to a stranger).
    d = ir.parse_decision(
        f'{{"involve_human": true, "user_id": "{uuid.uuid4()}"}}', {real}
    )
    assert d.involve_human and d.user_id is None

    # Garbage → no involvement.
    assert ir.parse_decision("not json", {real}).involve_human is False


# ── route (over DB) ────────────────────────────────────────────────────────────
async def _seed(session_factory, *, founder_involvement="approve big spend"):
    from app.models import Company, Membership, User
    from app.models.enums import CompanyStatus

    async with session_factory() as db:
        founder = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(founder)
        await db.flush()
        company = Company(owner_user_id=founder.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Membership(user_id=founder.id, company_id=company.id,
                          role=MembershipRole.founder, involvement=founder_involvement))
        await db.commit()
        return company.id, founder.id


@requires_db
async def test_route_no_stated_involvement_stays_autonomous(session_factory):
    company_id, _ = await _seed(session_factory, founder_involvement=None)
    async with session_factory() as db:
        d = await ir.route(db, company_id=company_id,
                           subject=ir.RoutingSubject(kind="task", summary="write a blog post"))
    assert d.involve_human is False


@requires_db
async def test_route_falls_back_to_founder_without_a_model(session_factory, monkeypatch):
    company_id, founder_id = await _seed(session_factory)

    async def _no_provider(*a, **k):
        return None

    monkeypatch.setattr("app.services.involvement_router.apikeys.resolve_active_provider",
                        _no_provider)
    async with session_factory() as db:
        d = await ir.route(db, company_id=company_id,
                           subject=ir.RoutingSubject(kind="spend_approval", summary="$5,000 ad buy"))
    assert d.involve_human is True and d.user_id == founder_id


@requires_db
async def test_route_uses_the_model_verdict(session_factory, monkeypatch):
    company_id, founder_id = await _seed(session_factory)

    provider = SimpleNamespace(default_models={"cheap": "m"})
    monkeypatch.setattr(
        "app.services.involvement_router.apikeys.resolve_active_provider",
        lambda *a, **k: _await(SimpleNamespace(provider=provider, api_key="k", funding_user_id=None)),
    )

    async def _fake_run_llm(self, *a, **k):
        return SimpleNamespace(text=f'{{"involve_human": true, "user_id": "{founder_id}", "reason": "big spend"}}')

    monkeypatch.setattr("app.services.involvement_router.CostMeter.run_llm", _fake_run_llm)
    async with session_factory() as db:
        d = await ir.route(db, company_id=company_id,
                           subject=ir.RoutingSubject(kind="spend_approval", summary="$5,000 ad buy"))
    assert d.involve_human is True and d.user_id == founder_id and "big spend" in d.reason


async def _await(value):
    return value
