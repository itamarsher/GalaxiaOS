"""arq cron entrypoints. Each iterates active companies in its own session."""

from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Company
from app.models.enums import CompanyStatus
from app.services import copilot
from app.services import runway as runway_svc


async def _active_company_ids() -> list:
    async with SessionLocal() as db:
        rows = await db.scalars(
            select(Company.id).where(Company.status == CompanyStatus.active)
        )
        return list(rows)


async def recompute_runway(ctx: dict) -> dict:
    count = 0
    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await runway_svc.recompute(db, company_id)
            await db.commit()
            count += 1
    return {"companies": count}


async def generate_digests(ctx: dict) -> dict:
    count = 0
    for company_id in await _active_company_ids():
        async with SessionLocal() as db:
            await copilot.generate_digest(db, company_id=company_id)
            await db.commit()
            count += 1
    return {"companies": count}
