"""Authentication: Google SSO (default), email/password fallback, current user.

Google SSO is the primary sign-in path; email/password stays as a fallback so
existing accounts and scripted/dev logins keep working. The Google flow and the
account-wide Google Drive grant share one callback (``/auth/google/callback``); the
signed ``state`` tells the callback which flow it is completing.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentUser, DbDep
from app.integrations import google_oauth
from app.integrations.files import FileProviderError
from app.models import User
from app.schemas import (
    AuthorizeUrlOut,
    GoogleAuthStatusOut,
    SignupRequest,
    TokenResponse,
    UserOut,
)
from app.security import (
    create_access_token,
    create_login_state,
    create_user_drive_state,
    decode_user_drive_state,
    hash_password,
    verify_login_state,
    verify_password,
)
from app.services import google_auth, invites, user_drive

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse)
async def signup(body: SignupRequest, db: DbDep) -> TokenResponse:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=body.email, hashed_password=hash_password(body.password))
    db.add(user)
    await db.flush()
    # Materialise any team invites addressed to this email (they join by signing up).
    await invites.consume_for_user(db, user)
    await db.commit()
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(db: DbDep, form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == form.username))
    # ``hashed_password`` is null for SSO-only accounts — reject password login for
    # them rather than passing ``None`` to the verifier.
    if user is None or not user.hashed_password or not verify_password(
        form.password, user.hashed_password
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    # Pick up any invites created for this email since they last signed in.
    if await invites.consume_for_user(db, user):
        await db.commit()
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


# ── Google SSO ────────────────────────────────────────────────────────────────


@router.get("/google/status", response_model=GoogleAuthStatusOut)
async def google_status() -> GoogleAuthStatusOut:
    """Whether the Google sign-in button should be shown (always 200)."""
    return GoogleAuthStatusOut(enabled=google_oauth.connect_configured())


@router.get("/google/authorize", response_model=AuthorizeUrlOut)
async def google_authorize() -> AuthorizeUrlOut:
    """Begin "Sign in with Google": return the consent URL to redirect to."""
    if not google_oauth.connect_configured():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Google sign-in is not enabled on this deployment."
        )
    url = google_oauth.login_authorize_url(
        client_id=settings.google_oauth_client_id,
        redirect_uri=google_oauth.callback_uri(settings.public_api_base_url),
        state=create_login_state(),
    )
    return AuthorizeUrlOut(authorize_url=url)


@router.get("/google/drive/connect", response_model=AuthorizeUrlOut)
async def google_drive_connect(user: CurrentUser) -> AuthorizeUrlOut:
    """Begin the account-wide Drive grant for the signed-in user."""
    if not google_oauth.connect_configured():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Google Drive connect is not enabled on this deployment."
        )
    url = google_oauth.drive_authorize_url(
        client_id=settings.google_oauth_client_id,
        redirect_uri=google_oauth.callback_uri(settings.public_api_base_url),
        state=create_user_drive_state(user.id),
    )
    return AuthorizeUrlOut(authorize_url=url)


@router.get("/google/drive")
async def google_drive_status(user: CurrentUser, db: DbDep) -> dict:
    """Account-wide Drive status for the signed-in user (never returns the token)."""
    return await user_drive.user_drive_status(db, user_id=user.id)


@router.delete("/google/drive", status_code=status.HTTP_204_NO_CONTENT)
async def google_drive_disconnect(user: CurrentUser, db: DbDep):
    removed = await user_drive.clear_user_drive(db, user_id=user.id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Google Drive connected")
    await db.commit()


def _web_redirect(path: str, **params: str) -> RedirectResponse:
    """Bounce the browser back to a page on the web app with a status flag."""
    base = f"{settings.web_base_url.rstrip('/')}{path}"
    sep = "&" if "?" in base else "?"
    query = urlencode(params)
    target = f"{base}{sep}{query}" if query else base
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/google/callback")
async def google_callback(
    db: DbDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Shared Google OAuth callback for both login and the account-wide Drive grant.

    The signed ``state`` selects the flow: a login state (no subject) completes
    sign-in and hands a fresh access token back to the web app; a user-drive state
    (carrying the user id) stores the refresh token and returns to the app. The
    callback is unauthenticated (it's Google's redirect) — the signed state is the
    CSRF defense and, for Drive, the attribution.
    """
    redirect_uri = google_oauth.callback_uri(settings.public_api_base_url)

    # Drive grant? (state carries the user id under the drive audience)
    drive_user_id = decode_user_drive_state(state) if state else None
    if drive_user_id is not None:
        if error or not code:
            return _web_redirect("/", drive=error or "denied")
        try:
            refresh_token = await google_oauth.exchange_code_for_refresh_token(
                code=code, redirect_uri=redirect_uri
            )
            await user_drive.set_user_drive_refresh(
                db, user_id=drive_user_id, refresh_token=refresh_token
            )
            await db.commit()
        except FileProviderError:
            await db.rollback()
            return _web_redirect("/", drive="error")
        return _web_redirect("/", drive="connected")

    # Otherwise it must be a login state.
    if not state or not verify_login_state(state):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth state.")
    if error or not code:
        return _web_redirect("/", auth=error or "denied")
    try:
        identity = await google_oauth.exchange_code_for_identity(
            code=code, redirect_uri=redirect_uri
        )
    except FileProviderError:
        return _web_redirect("/", auth="error")
    user = await google_auth.upsert_google_user(db, identity)
    # Team invites addressed to this Google email are consumed on sign-in.
    await invites.consume_for_user(db, user)
    await db.commit()
    # Hand the freshly-minted access token back to the SPA via the URL; the page
    # reads and stores it, then strips it from the address bar.
    return _web_redirect("/", token=create_access_token(user.id))
