"""Signed founder connection tokens for a user's own AI operator.

The agent-first pivot: a user connects their AI to GalaxiaOS once, and that AI
registers, onboards, launches, and steers companies on their behalf — including
resolving the founder decisions that gate the work (plans, hires, spend, external
comms). A founder token is the credential that AI presents to the Founder MCP
(``/connect/founder``).

Unlike a function token (bound to one ``(company, agent)`` pair), a founder token
is bound to a **user** — the AI acts as that founder across every company they
own, and can create new ones. That is a powerful credential (full account power),
so it is only mintable by the already-authenticated user, and every company-scoped
call still re-checks that the user is a member of the target company.

Stateless: an HMAC-SHA256 signature over ``"founder:{user_id}"`` keyed by
``ABOS_FOUNDER_CONNECTION_SECRET``. When the secret is unset the Founder MCP is
disabled — minting raises and verification rejects — so it is strictly opt-in.
Rotation/revocation is by rotating the secret (invalidates all tokens).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from app.config import settings


class TokensDisabled(RuntimeError):
    """Raised when minting is attempted without a configured signing secret."""


def _secret() -> bytes | None:
    raw = settings.founder_connection_secret
    return raw.encode() if raw else None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def mint(*, user_id: uuid.UUID) -> str:
    """A signed founder connection token binding an AI operator to ``user_id``."""
    secret = _secret()
    if secret is None:
        raise TokensDisabled(
            "founder connection tokens are not configured (set ABOS_FOUNDER_CONNECTION_SECRET)"
        )
    payload = f"founder:{user_id}".encode()
    sig = hmac.new(secret, payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(sig)}"


def verify(token: str) -> uuid.UUID | None:
    """Return the ``user_id`` for a valid token, else ``None``.

    Returns ``None`` (never raises) for a missing secret, a malformed token, or a
    bad signature — every failure is an authentication rejection.
    """
    secret = _secret()
    if secret is None or not token or "." not in token:
        return None
    p_b64, _, s_b64 = token.partition(".")
    try:
        payload = _unb64(p_b64)
        sig = _unb64(s_b64)
    except (ValueError, TypeError):
        return None
    expected = hmac.new(secret, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        prefix, _, user_str = payload.decode().partition(":")
        if prefix != "founder":
            return None
        return uuid.UUID(user_str)
    except (ValueError, UnicodeDecodeError):
        return None
