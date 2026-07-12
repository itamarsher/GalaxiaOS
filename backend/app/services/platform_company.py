"""The platform (dogfooding) company — GalaxiaOS operating on itself.

Exactly one :class:`~app.models.company.Company` carries ``is_platform=True``. It
is the reference business whose agents dogfood the product: their unmet needs feed
the shared feature-request backlog, and its Platform agent is the ONLY actor
authorized to promote that backlog into real tracker issues (see
:mod:`app.runtime.tools.platform`). The same company alone may use the deployment's
global Render key (:mod:`app.runtime.tools.render_ops`), and the platform cron jobs
(:mod:`app.jobs.scheduled`) run on its behalf.

This replaces the old fixed founder-user + fixed company-id bootstrap: rather than
provisioning a synthetic ``founder@galaxia.abos`` account at startup and keying the
promoter gate to that user id, the platform role is a flag on a real company. The
first company onboarded in a deployment is designated automatically
(:func:`designate_if_first`), so the founder's own company becomes the dogfooding
company — no synthetic account, and the designation survives ownership changes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company


async def platform_company_id(db: AsyncSession) -> uuid.UUID | None:
    """The id of the platform company, or ``None`` if none is designated yet."""
    return await db.scalar(select(Company.id).where(Company.is_platform.is_(True)))


async def is_platform_company(db: AsyncSession, company_id: uuid.UUID) -> bool:
    """True if ``company_id`` is the designated platform company."""
    flag = await db.scalar(
        select(Company.is_platform).where(Company.id == company_id)
    )
    return bool(flag)


async def designate_if_first(db: AsyncSession, company: Company) -> bool:
    """Flag ``company`` as the platform company iff none exists yet.

    Called when a company is created during onboarding: the first company in a
    fresh deployment becomes the dogfooding company that drives the demand→issue
    loop. A no-op (returns ``False``) once a platform company already exists, so
    later companies are ordinary tenants. The partial-unique index is the hard
    backstop against a race creating two.
    """
    if await platform_company_id(db) is not None:
        return False
    company.is_platform = True
    await db.flush()
    return True
