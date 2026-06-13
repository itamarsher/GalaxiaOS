"""Rate limiting + observability tests (no DB, no network)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability import RequestContextMiddleware
from app.ratelimit import InMemoryRateLimiter, RateLimitMiddleware


async def test_in_memory_limiter_blocks_after_limit_and_refills():
    clock = {"t": 0.0}
    rl = InMemoryRateLimiter(limit=2, window_seconds=60, clock=lambda: clock["t"])

    assert (await rl.allow("k"))[0] is True
    assert (await rl.allow("k"))[0] is True
    allowed, retry_after = await rl.allow("k")
    assert allowed is False and retry_after > 0  # third hit blocked within window

    clock["t"] = 61.0  # window elapsed -> counter resets
    assert (await rl.allow("k"))[0] is True


async def test_in_memory_limiter_is_per_key():
    rl = InMemoryRateLimiter(limit=1, window_seconds=60, clock=lambda: 0.0)
    assert (await rl.allow("a"))[0] is True
    assert (await rl.allow("b"))[0] is True  # different key, own budget
    assert (await rl.allow("a"))[0] is False


def _app_with_limit(limit: int) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=InMemoryRateLimiter(limit, 60))
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def test_request_id_header_and_echo():
    client = TestClient(_app_with_limit(100))
    r = client.get("/ping")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")
    # An inbound id is honored.
    r2 = client.get("/ping", headers={"X-Request-ID": "trace-abc"})
    assert r2.headers["X-Request-ID"] == "trace-abc"


def test_http_429_after_limit_and_health_exempt():
    client = TestClient(_app_with_limit(2))
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    blocked = client.get("/ping")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    # /health is exempt from rate limiting even after the limit is hit.
    assert client.get("/health").status_code == 200
