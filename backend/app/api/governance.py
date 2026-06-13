"""Governance endpoints: policies, circuit breakers, reputation."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, DbDep
from app.models import CircuitBreaker, Policy, ReputationScore
from app.models.enums import BreakerState, PolicyEffect, PolicyScope
from app.schemas import (
    BreakerOut,
    PolicyCreateRequest,
    PolicyOut,
    ReputationOut,
)

router = APIRouter(prefix="/companies/{company_id}", tags=["governance"])


@router.get("/policies", response_model=list[PolicyOut])
async def list_policies(company: CompanyDep, db: DbDep):
    return (
        await db.scalars(
            select(Policy).where(Policy.company_id == company.id).order_by(Policy.priority)
        )
    ).all()


@router.post("/policies", response_model=PolicyOut)
async def create_policy(company: CompanyDep, body: PolicyCreateRequest, db: DbDep):
    policy = Policy(
        company_id=company.id,
        name=body.name,
        scope=PolicyScope(body.scope),
        rule=body.rule,
        effect=PolicyEffect(body.effect),
        priority=body.priority,
        enabled=body.enabled,
    )
    db.add(policy)
    await db.commit()
    return policy


@router.get("/circuit-breakers", response_model=list[BreakerOut])
async def list_breakers(company: CompanyDep, db: DbDep):
    return (
        await db.scalars(select(CircuitBreaker).where(CircuitBreaker.company_id == company.id))
    ).all()


@router.post("/circuit-breakers/{breaker_id}/reset", response_model=BreakerOut)
async def reset_breaker(company: CompanyDep, breaker_id: uuid.UUID, db: DbDep):
    breaker = await db.scalar(
        select(CircuitBreaker).where(
            CircuitBreaker.company_id == company.id, CircuitBreaker.id == breaker_id
        )
    )
    if breaker is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Breaker not found")
    breaker.state = BreakerState.armed
    breaker.tripped_at = None
    breaker.tripped_reason = None
    await db.commit()
    return breaker


@router.get("/reputation", response_model=list[ReputationOut])
async def list_reputation(company: CompanyDep, db: DbDep):
    return (
        await db.scalars(
            select(ReputationScore).where(ReputationScore.company_id == company.id)
        )
    ).all()
