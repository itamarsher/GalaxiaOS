"""The operator (dogfooding) company — GalaxiaOS operating on itself.

A deployment MAY name one ordinary company as its **operator company** via
``ABOS_PLATFORM_COMPANY_ID``. That company's Platform agent is the only actor
authorized to promote the shared feature-request backlog into real tracker issues
(see :mod:`app.runtime.tools.platform`), it alone may use the deployment's global
Render key (:mod:`app.runtime.tools.render_ops`), and the operator cron jobs
(:mod:`app.jobs.scheduled`) run on its behalf.

This used to be a magic ``is_platform`` flag auto-set on the first company onboarded.
It is now **explicit configuration** pointing at a normal company: the dogfooding
company is created through ordinary onboarding like any tenant (funded by its own
keys, metered like any tenant), and an operator is a deployment choice, not a hidden
database state. When the setting is unset, there is no operator company — the
promoter/monitor crons no-op and the global Render fallback is off.
"""

from __future__ import annotations

import uuid

from app.config import settings


def platform_company_id() -> uuid.UUID | None:
    """The configured operator company id, or ``None`` if unset/invalid."""
    raw = (settings.platform_company_id or "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def is_platform_company(company_id: uuid.UUID) -> bool:
    """True if ``company_id`` is the configured operator company."""
    pid = platform_company_id()
    return pid is not None and pid == company_id
