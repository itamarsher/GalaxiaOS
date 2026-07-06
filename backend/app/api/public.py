"""Public, unauthenticated endpoints served to the open internet.

Today this is just the landing-page lead-capture sink: a published page is a
static asset on a third-party host (Cloudflare Pages), so its built-in
email/waitlist form POSTs here. Everything is keyed off the (unguessable) site id
in the URL — there is no auth/company context on these requests — and the tenant
is derived from the resolved row before any write.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Form, HTTPException, status
from fastapi.responses import HTMLResponse

from app.deps import DbDep
from app.services import sites as sites_svc

router = APIRouter(prefix="/p", tags=["public"])

# Deliberately loose: just enough to reject obvious non-emails without bouncing
# unusual-but-valid addresses. The list is for humans, not RFC validation.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/sites/{site_id}/subscribe", response_class=HTMLResponse)
async def subscribe(
    site_id: uuid.UUID,
    db: DbDep,
    email: str = Form(""),
    name: str = Form(""),
    message: str = Form(""),
    website: str = Form(""),  # honeypot — see render._capture_form_html
) -> HTMLResponse:
    """Capture an email signup from a published landing page's form."""
    site = await sites_svc.get_site_by_id(db, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown page")

    back_url = site.deployment_url

    # A filled honeypot means a bot: accept silently (show the same thank-you) but
    # store nothing, so scripts get no signal that they were filtered.
    if website.strip():
        return HTMLResponse(sites_svc.render_thanks_html(site_title=site.title, back_url=back_url))

    email = email.strip()
    if not _EMAIL_RE.match(email):
        return HTMLResponse(
            sites_svc.render_page_invalid_email(site_title=site.title, back_url=back_url),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    await sites_svc.capture_lead(db, site=site, email=email, name=name, message=message)
    await db.commit()
    return HTMLResponse(sites_svc.render_thanks_html(site_title=site.title, back_url=back_url))
