"""Google SSO: pure OAuth helpers and the signed-state round-trips (all offline)."""

from __future__ import annotations

import pytest

from app import security
from app.config import settings
from app.integrations import google_oauth
from app.integrations.files import FileProviderError


def test_login_authorize_url_requests_identity_scopes():
    url = google_oauth.login_authorize_url(
        client_id="cid", redirect_uri="https://api/x/auth/google/callback", state="st"
    )
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    # Identity scopes, no offline access (login reads the profile once).
    assert "scope=openid+email+profile" in url
    assert "access_type=offline" not in url
    assert "state=st" in url


def test_drive_authorize_url_requests_offline_drive_scope():
    url = google_oauth.drive_authorize_url(
        client_id="cid", redirect_uri="https://api/x/auth/google/callback", state="st"
    )
    assert "drive.file" in url
    # Offline + consent guarantee a refresh token even on re-authorization.
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_parse_userinfo_extracts_identity():
    identity = google_oauth.parse_userinfo(
        200, {"sub": "abc123", "email": "Founder@Example.com", "name": "Ada"}
    )
    assert identity.sub == "abc123"
    assert identity.email == "founder@example.com"  # normalized lower-case
    assert identity.name == "Ada"


def test_parse_userinfo_requires_sub_and_email():
    with pytest.raises(FileProviderError):
        google_oauth.parse_userinfo(200, {"email": "x@y.com"})  # no sub
    with pytest.raises(FileProviderError):
        google_oauth.parse_userinfo(200, {"sub": "s"})  # no email


def test_parse_userinfo_raises_on_error_status():
    with pytest.raises(FileProviderError):
        google_oauth.parse_userinfo(401, {"error": "invalid_token"})


def test_parse_refresh_token_requires_a_token():
    assert google_oauth.parse_refresh_token(200, {"refresh_token": "rt"}) == "rt"
    with pytest.raises(FileProviderError):
        google_oauth.parse_refresh_token(200, {"access_token": "at"})  # no refresh token


def test_connect_configured_reflects_client_credentials(monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "")
    assert google_oauth.connect_configured() is False
    monkeypatch.setattr(settings, "google_oauth_client_id", "cid")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "secret")
    assert google_oauth.connect_configured() is True


# ── signed OAuth-state round-trips (CSRF + attribution) ───────────────────────


def test_login_state_round_trip(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    state = security.create_login_state()
    assert security.verify_login_state(state) is True
    # A user-drive state must NOT validate as a login state (distinct audiences).
    import uuid

    other = security.create_user_drive_state(uuid.uuid4())
    assert security.verify_login_state(other) is False


def test_user_drive_state_round_trip(monkeypatch):
    import uuid

    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    uid = uuid.uuid4()
    state = security.create_user_drive_state(uid)
    assert security.decode_user_drive_state(state) == uid
    # A login state carries no subject, so it decodes to None here.
    assert security.decode_user_drive_state(security.create_login_state()) is None
