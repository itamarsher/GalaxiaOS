"""The free-tier keep-warm self-ping job."""

from __future__ import annotations

from app.config import settings
from app.jobs.scheduled import keep_warm


async def test_keep_warm_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "keep_warm_enabled", False)
    assert await keep_warm({}) == {"skipped": True}


async def test_keep_warm_skips_without_public_url(monkeypatch):
    monkeypatch.setattr(settings, "keep_warm_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "")
    assert await keep_warm({}) == {"skipped": "no_public_url"}


async def test_keep_warm_pings_public_health(monkeypatch):
    monkeypatch.setattr(settings, "keep_warm_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://example.test/")

    calls = {}

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            calls["url"] = url
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    out = await keep_warm({})
    assert out == {"pinged": "https://example.test/health", "status": 200}
    assert calls["url"] == "https://example.test/health"
