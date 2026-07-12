"""Google OAuth — "Sign in with Google" identity, and the account-wide Drive grant.

Two flows share the deployment's single Google Cloud OAuth client (the same
``client_id`` / ``client_secret`` the per-company Drive connect already uses) and
one callback endpoint (``/auth/google/callback``):

- **Login** (``login_authorize_url``): request ``openid email profile`` to identify
  the person. This is the default sign-up/sign-in button. No refresh token is
  needed — we only read the profile once, mint our own JWT, and are done.
- **Account-wide Drive** (``drive_authorize_url``): request ``drive.file`` with
  ``access_type=offline`` so Google returns a durable refresh token, stored on the
  *user* (not a company) — connect Drive once and every business the user launches
  files into it. This is the incremental grant, requested after login.

Everything that shapes a request/response is a pure, unit-testable helper so the
flow is covered offline without hitting Google.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.integrations.files import FileProviderError

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
# OpenID Connect userinfo — returns the account's stable ``sub``, ``email`` and
# ``name`` given a login access token. Avoids verifying the id_token signature.
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# Identity scopes for login, and the least-privilege Drive scope for the file store
# (files the app creates — enough to file and read our own documents).
_LOGIN_SCOPE = "openid email profile"
_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

# Single callback for both flows; the signed ``state`` carries which one it is.
_CALLBACK_PATH = "/auth/google/callback"


def connect_configured() -> bool:
    """True when the deployment has a Google OAuth app (so the buttons appear)."""
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)


def callback_uri(api_base_url: str) -> str:
    """The OAuth redirect URI to register on the client (used by both flows)."""
    return f"{api_base_url.rstrip('/')}{_CALLBACK_PATH}"


def login_authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Google's consent URL for "Sign in with Google" (identity only)."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _LOGIN_SCOPE,
        # Let the user pick which Google account to use rather than silently
        # reusing a signed-in one.
        "prompt": "select_account",
        "state": state,
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def drive_authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Google's consent URL for the account-wide Drive grant.

    ``access_type=offline`` + ``prompt=consent`` guarantee a ``refresh_token`` is
    returned even on a repeat authorization (Google omits it otherwise).
    """
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _DRIVE_SCOPE,
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


@dataclass(frozen=True)
class GoogleIdentity:
    """The profile fields we persist from a Google login."""

    sub: str
    email: str
    name: str | None


def parse_token_response(status_code: int, body: dict) -> dict:
    """Return the raw token response, raising on an error status."""
    if status_code >= 400:
        detail = body.get("error_description") or body.get("error") or f"HTTP {status_code}"
        raise FileProviderError(f"Google authorization failed: {detail}")
    return body


def parse_refresh_token(status_code: int, body: dict) -> str:
    """Pull the ``refresh_token`` out of the token response (Drive grant)."""
    parse_token_response(status_code, body)
    token = body.get("refresh_token")
    if not token:
        raise FileProviderError(
            "Google did not return a refresh token — re-authorize granting offline access."
        )
    return str(token)


def parse_userinfo(status_code: int, body: dict) -> GoogleIdentity:
    """Build a :class:`GoogleIdentity` from the userinfo response.

    Requires a stable ``sub`` and an ``email`` — without them we cannot key or
    contact the account, so treat their absence as an auth failure.
    """
    if status_code >= 400:
        detail = body.get("error_description") or body.get("error") or f"HTTP {status_code}"
        raise FileProviderError(f"Google userinfo failed: {detail}")
    sub = str(body.get("sub") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    if not sub or not email:
        raise FileProviderError("Google did not return a usable account (missing sub/email).")
    name = str(body.get("name") or "").strip() or None
    return GoogleIdentity(sub=sub, email=email, name=name)


async def _exchange_code(*, code: str, redirect_uri: str) -> dict:
    """Trade a one-time ``code`` for the token response (server-side)."""
    if not connect_configured():
        raise FileProviderError("Google sign-in is not configured on this deployment.")
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
    return parse_token_response(resp.status_code, body)


async def exchange_code_for_identity(*, code: str, redirect_uri: str) -> GoogleIdentity:
    """Complete the login flow: code → access token → userinfo → identity."""
    tokens = await _exchange_code(code=code, redirect_uri=redirect_uri)
    access_token = str(tokens.get("access_token") or "")
    if not access_token:
        raise FileProviderError("Google did not return an access token.")
    try:
        async with httpx.AsyncClient(timeout=settings.web_search_timeout_seconds) as client:
            resp = await client.get(
                _USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            body = resp.json() if resp.content else {}
    except httpx.HTTPError as exc:
        raise FileProviderError(f"Google userinfo request failed: {exc}") from exc
    except ValueError as exc:
        raise FileProviderError(f"Google userinfo returned non-JSON: {exc}") from exc
    return parse_userinfo(resp.status_code, body)


async def exchange_code_for_refresh_token(*, code: str, redirect_uri: str) -> str:
    """Complete the Drive grant: code → durable refresh token."""
    tokens = await _exchange_code(code=code, redirect_uri=redirect_uri)
    return parse_refresh_token(200, tokens)
