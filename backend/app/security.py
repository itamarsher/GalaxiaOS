"""Password hashing and JWT issuance/verification."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def _password_bytes(password: str) -> bytes:
    """Encode a password for bcrypt, truncated to bcrypt's 72-byte limit.

    bcrypt only considers the first 72 bytes and (since bcrypt 5.0) raises on
    longer inputs, so we truncate explicitly. This matches passlib's historical
    silent truncation, keeping previously stored hashes verifiable.
    """
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(password), hashed.encode("utf-8"))
    except ValueError:
        # Malformed/unsupported stored hash — treat as a failed verification
        # rather than a 500.
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        sub = payload.get("sub")
        return uuid.UUID(sub) if sub else None
    except (JWTError, ValueError):
        return None


# OAuth ``state`` for the Google Drive connect flow. It is a short-lived JWT
# carrying the company id, signed with the same secret as access tokens: the
# unauthenticated callback can trust the company id without a bearer token (the
# state proves an authenticated member started the flow), which is the standard
# CSRF defense for an OAuth redirect. A dedicated ``aud`` keeps it from being
# accepted anywhere an access token is.
_OAUTH_STATE_AUDIENCE = "gdrive-oauth"


# ── Telegram connect token ────────────────────────────────────────────────────
# Carried in the ``/start <token>`` deep-link a founder taps to link their Telegram
# chat to a company. A dedicated ``aud`` keeps it from being replayed as anything
# else; short-lived because it only has to survive the tap-to-Telegram round trip.
_TELEGRAM_CONNECT_AUDIENCE = "telegram-connect"


def create_telegram_connect_token(company_id: uuid.UUID, *, minutes: int = 15) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    payload = {"sub": str(company_id), "exp": expire, "aud": _TELEGRAM_CONNECT_AUDIENCE}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_telegram_connect_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=_TELEGRAM_CONNECT_AUDIENCE,
            options={"require_aud": True},
        )
        sub = payload.get("sub")
        return uuid.UUID(sub) if sub else None
    except (JWTError, ValueError):
        return None


def create_oauth_state(company_id: uuid.UUID, *, minutes: int = 10) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    payload = {"sub": str(company_id), "exp": expire, "aud": _OAUTH_STATE_AUDIENCE}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_oauth_state(state: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(
            state,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=_OAUTH_STATE_AUDIENCE,
            # Require the aud claim so a plain access token (which has none) can
            # never be replayed as OAuth state.
            options={"require_aud": True},
        )
        sub = payload.get("sub")
        return uuid.UUID(sub) if sub else None
    except (JWTError, ValueError):
        return None


# ── Google SSO login + account-wide Drive OAuth states ────────────────────────
# The Google "Sign in with Google" flow and the account-wide Drive grant share one
# callback endpoint (``/auth/google/callback``); the signed ``state`` carries the
# intent (its ``aud``) so the callback knows which flow it is completing. Login
# state carries no subject (there is no user yet — it's pure CSRF protection);
# Drive state carries the authenticated user's id so the (unauthenticated) callback
# can attribute the refresh token.
_LOGIN_STATE_AUDIENCE = "google-login"
_USER_DRIVE_STATE_AUDIENCE = "google-user-drive"


def create_login_state(*, minutes: int = 10) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    payload = {"exp": expire, "aud": _LOGIN_STATE_AUDIENCE}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_login_state(state: str) -> bool:
    try:
        jwt.decode(
            state,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=_LOGIN_STATE_AUDIENCE,
            options={"require_aud": True},
        )
        return True
    except JWTError:
        return False


def create_user_drive_state(user_id: uuid.UUID, *, minutes: int = 10) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    payload = {"sub": str(user_id), "exp": expire, "aud": _USER_DRIVE_STATE_AUDIENCE}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_user_drive_state(state: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(
            state,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=_USER_DRIVE_STATE_AUDIENCE,
            options={"require_aud": True},
        )
        sub = payload.get("sub")
        return uuid.UUID(sub) if sub else None
    except (JWTError, ValueError):
        return None
