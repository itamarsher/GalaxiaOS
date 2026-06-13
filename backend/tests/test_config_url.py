"""Tests for managed-provider database URL normalization (pure)."""

from __future__ import annotations

from app.config import normalize_db_url


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
