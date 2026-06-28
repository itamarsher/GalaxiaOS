"""Google Drive one-click connect — the OAuth authorization-code flow.

This is the "Connect with Google" button's backend. Unlike the rest of the Drive
adapter (which is bring-your-own *refresh token*), the OAuth **app** is owned by
the deployment: a single Google Cloud OAuth client whose ``client_id`` /
``client_secret`` live in :mod:`app.config` (``ABOS_GOOGLE_OAUTH_CLIENT_ID`` /
``ABOS_GOOGLE_OAUTH_CLIENT_SECRET``). A founder clicks Connect, authorizes ABOS on
Google's consent screen, and Google redirects back with a one-time ``code`` that we
exchange — server-side, using the deployment secret — for a long-lived
``refresh_token`` stored per-company. The founder never touches the Cloud Console.

Least privilege: we request only ``drive.file`` (files the app creates), which is
all ABOS needs to file documents under ``.galaxia/<company>/…`` and read them back.

Everything that shapes a request/response is a pure, unit-testable helper
(:func:`authorize_url`, :func:`redirect_uri`, :func:`exchange_form`,
:func:`parse_exchange`) so the flow is covered offline without hitting Google.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.config import settings
from app.integrations.files import FileProviderError

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
# files the app creates — enough to file and read ABOS's own documents, and the
# scope Google verifies most readily.
_SCOPE = "https://www.googleapis.com/auth/drive.file"
_CALLBACK_PATH = "/integrations/google-drive/callback"


def connect_configured() -> bool:
    """True when the deployment has a Google OAuth app (so Connect is available)."""
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)


def redirect_uri(api_base_url: str) -> str:
    """The OAuth redirect URI to register on the client (and pass on every call)."""
    return f"{api_base_url.rstrip('/')}{_CALLBACK_PATH}"


def authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Google's consent-screen URL to send the founder's browser to.

    ``access_type=offline`` + ``prompt=consent`` guarantee a ``refresh_token`` is
    returned even on a repeat authorization (Google omits it otherwise).
    """
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_form(
    *, code: str, client_id: str, client_secret: str, redirect_uri: str
) -> dict[str, str]:
    """The form body that trades an authorization ``code`` for tokens."""
    return {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }


def parse_exchange(status_code: int, body: dict) -> str:
    """Pull the ``refresh_token`` out of Google's code-exchange response.

    Raises :class:`FileProviderError` on an error response or when no refresh
    token came back (which ``prompt=consent`` is meant to prevent).
    """
    if status_code >= 400:
        detail = body.get("error_description") or body.get("error") or f"HTTP {status_code}"
        raise FileProviderError(f"Google authorization failed: {detail}")
    token = body.get("refresh_token")
    if not token:
        raise FileProviderError(
            "Google did not return a refresh token — re-authorize granting offline access."
        )
    return str(token)


async def exchange_code_for_refresh_token(*, code: str, redirect_uri: str) -> str:
    """Exchange a one-time ``code`` for a durable refresh token (server-side)."""
    if not connect_configured():
        raise FileProviderError("Google Drive connect is not configured on this deployment.")
    form = exchange_form(
        code=code,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        redirect_uri=redirect_uri,
    )
    try:
        async with httpx.AsyncClient(timeout=settings.web_search_timeout_seconds) as client:
            resp = await client.post(_TOKEN_URL, data=form)
            body = resp.json() if resp.content else {}
    except httpx.HTTPError as exc:
        raise FileProviderError(f"Google token exchange failed: {exc}") from exc
    except ValueError as exc:
        raise FileProviderError(f"Google token exchange returned non-JSON: {exc}") from exc
    return parse_exchange(resp.status_code, body)
