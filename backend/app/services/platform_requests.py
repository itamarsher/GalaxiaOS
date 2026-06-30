"""Founder-initiated platform requests (bug reports / capability requests).

Agents file these via the ``report_bug`` / ``request_capability`` tools, but the
founder also needs to file one directly when chatting with the copilot or an
agent ("request web search"). Both paths now land in the internal feature-request
backlog (:mod:`app.services.feature_requests`) rather than immediately waking the
Platform agent: the request is deduplicated and voted on, and a gated promoter in
the abos company later turns accrued demand into a real tracker issue.

This module is the founder/copilot entry point — it threads the requesting
``user_id`` (when known) through to the backlog so we can track *which* users and
companies asked for *what*.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import feature_requests as fr_svc


async def file_request(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    kind: str,
    title: str,
    details: str,
    user_id: uuid.UUID | None = None,
) -> fr_svc.RequestOutcome | None:
    """Record a founder-initiated request in the backlog.

    Returns the :class:`~app.services.feature_requests.RequestOutcome` (so the
    caller can phrase a reply with the current demand), or ``None`` if the kind is
    unknown or the title is empty. The caller commits.
    """
    return await fr_svc.record_request(
        db,
        kind=kind,
        title=title,
        details=details,
        company_id=company_id,
        user_id=user_id,
    )
