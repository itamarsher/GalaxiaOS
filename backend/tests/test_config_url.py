"""Tests for managed-provider database URL normalization (pure)."""

from __future__ import annotations

from app.config import Settings, normalize_base_url, normalize_db_url
from app.integrations import google_oauth


def test_scheme_rewrite_to_asyncpg():
    assert normalize_db_url("postgres://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"
    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_already_asyncpg_is_unchanged():
    url = "postgresql+asyncpg://u:p@h:5432/db"
    assert normalize_db_url(url) == url


def test_sslmode_mapped_and_channel_binding_dropped():
    out = normalize_db_url("postgres://u:p@h/db?sslmode=require&channel_binding=require")
    assert out.startswith("postgresql+asyncpg://u:p@h/db?")
    assert "ssl=require" in out
    assert "channel_binding" not in out
    assert "sslmode" not in out


def test_sslmode_disable_is_not_mapped():
    out = normalize_db_url("postgresql://u:p@h/db?sslmode=disable")
    assert "ssl=" not in out


# ── public/web base URL normalization (OAuth redirect_uri mismatch) ───────────


def test_base_url_gets_https_scheme_when_missing():
    # The Render trap: the host-only value (as NEXT_PUBLIC_API_BASE_URL is
    # auto-wired) must become an absolute https:// origin.
    assert normalize_base_url("abos-api.onrender.com") == "https://abos-api.onrender.com"
    assert normalize_base_url("abos-api.onrender.com/") == "https://abos-api.onrender.com"


def test_base_url_trailing_slash_stripped_scheme_preserved():
    assert normalize_base_url("https://abos-api.onrender.com/") == "https://abos-api.onrender.com"
    assert normalize_base_url("http://api.example.com") == "http://api.example.com"


def test_base_url_local_hosts_keep_http():
    assert normalize_base_url("localhost:8000") == "http://localhost:8000"
    assert normalize_base_url("127.0.0.1:8000/") == "http://127.0.0.1:8000"


def test_base_url_empty_stays_empty():
    assert normalize_base_url("") == ""
    assert normalize_base_url("   ") == ""


def test_settings_normalizes_base_urls_from_env():
    # Values loaded from the environment run through the validator, so a
    # scheme-less host produces a redirect URI that matches the Google client.
    s = Settings(
        public_api_base_url="abos-api.onrender.com/",
        web_base_url="abos-web.onrender.com",
    )
    assert s.public_api_base_url == "https://abos-api.onrender.com"
    assert s.web_base_url == "https://abos-web.onrender.com"
    assert (
        google_oauth.callback_uri(s.public_api_base_url)
        == "https://abos-api.onrender.com/auth/google/callback"
    )
