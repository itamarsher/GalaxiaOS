"""Agent marketplace: browse the global catalog and hire listings into a company.

``GET /marketplace/listings`` exposes the company-agnostic catalog (auth only).
``POST /companies/{company_id}/marketplace/hire`` materialises a hired
:class:`~app.models.agent.Agent` (``source=hired``, ``backend_type=marketplace``)
that reports to the company's CEO and is billed per invocation by the
MarketplaceBackend.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Agent, AgentListing
from app.models.enums import AgentBackendType, AgentRole, AgentSource
from app.schemas import AgentListingOut, AgentOut, HireAgentRequest

catalog_router = APIRouter(prefix="/marketplace", tags=["marketplace"])
company_router = APIRouter(prefix="/companies/{company_id}/marketplace", tags=["marketplace"])


@catalog_router.get("/listings", response_model=list[AgentListingOut])
async def list_listings(user: CurrentUser, db: DbDep):
    """Global catalog of hireable agents (requires auth, not tenant-scoped)."""
    listings = (
        await db.scalars(select(AgentListing).order_by(AgentListing.price_cents))
    ).all()
    return listings


def _role_for(listing_role: str) -> AgentRole:
    try:
        return AgentRole(listing_role)
    except ValueError:
        return AgentRole.custom


@company_router.post("/hire", response_model=AgentOut)
async def hire_agent(company: CompanyDep, body: HireAgentRequest, db: DbDep):
    listing = await db.get(AgentListing, body.listing_id)
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")

    ceo = await db.scalar(
        select(Agent).where(Agent.company_id == company.id, Agent.role == AgentRole.ceo)
    )

    agent = Agent(
        company_id=company.id,
        role=_role_for(listing.role),
        name=listing.name,
        system_prompt="",
        source=AgentSource.hired,
        backend_type=AgentBackendType.marketplace,
        marketplace_listing_id=listing.id,
        invocation_price_cents=listing.price_cents,
        reports_to_agent_id=ceo.id if ceo else None,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent
