"""Business-function catalog — the building blocks a founder picks at onboarding.

``GET /functions/catalog`` exposes the company-agnostic catalog (auth only), so
the founder-facing picker can render the selectable building blocks (website,
social, outbound, inbound, brand, customer service, legal, finance, …) and the
oversight blocks GalaxiaOS guarantees. Read-only: it reflects the declarative
:mod:`app.services.function_catalog`, not per-tenant state. RFC 0002.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import CompanyDep, CurrentUser, DbDep
from app.services import function_catalog, function_improvement

router = APIRouter(prefix="/functions", tags=["functions"])
company_router = APIRouter(prefix="/companies/{company_id}", tags=["functions"])


def _serialize(fn: function_catalog.BusinessFunction) -> dict:
    return {
        "key": fn.key,
        "title": fn.title,
        "category": fn.category,
        "summary": fn.summary,
        "role": fn.role.value,
        "implementation": fn.implementation,
        "health_signals": list(fn.health_signals),
        "default_skills": list(fn.default_skills),
        "core": fn.core,
    }


@router.get("/catalog")
async def catalog(user: CurrentUser) -> dict:
    """The building blocks a founder can pick from, plus guaranteed oversight.

    ``selectable`` is the à-la-carte menu; ``core`` are the oversight blocks
    GalaxiaOS always spins up regardless of what the founder picks.
    """
    return {
        "selectable": [_serialize(f) for f in function_catalog.selectable_functions()],
        "core": [_serialize(f) for f in function_catalog.core_functions()],
    }


@company_router.get("/function-health")
async def function_health_board(company: CompanyDep, db: DbDep) -> dict:
    """This company's function-health board (RFC 0002): per-function KPI status +
    current/target from the seeded KRs, plus the agent-based KPIs. Read-only."""
    return await function_improvement.health_board(db, company_id=company.id)
