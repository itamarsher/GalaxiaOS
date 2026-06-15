"""Rate limiting + observability tests (no DB, no network)."""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.observability import RequestContextMiddleware
from app.providers.base import ProviderError
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


def _app_with_cors(limit: int, origins: list[str]) -> FastAPI:
    """Mirror create_app's middleware order: rate-limit → request-context → CORS
    (outermost), so every response — including 429s — carries CORS headers."""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=InMemoryRateLimiter(limit, 60))
    app.add_middleware(RequestContextMiddleware)
    allow_all = "*" in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


def test_cors_header_present_on_normal_response():
    client = TestClient(_app_with_cors(100, ["*"]))
    r = client.get("/ping", headers={"Origin": "https://abos-web.onrender.com"})
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == "*"


def test_cors_header_present_on_rate_limit_rejection():
    # The regression this fixes: with CORS outermost, a 429 still carries the
    # Access-Control-Allow-Origin header, so the browser surfaces the real 429
    # instead of masking it as an opaque CORS error.
    client = TestClient(_app_with_cors(1, ["*"]))
    origin = {"Origin": "https://abos-web.onrender.com"}
    assert client.get("/ping", headers=origin).status_code == 200
    blocked = client.get("/ping", headers=origin)
    assert blocked.status_code == 429
    assert blocked.headers["Access-Control-Allow-Origin"] == "*"


def test_cors_explicit_allowlist_reflects_origin_with_credentials():
    origin = "https://abos-web.onrender.com"
    client = TestClient(_app_with_cors(100, [origin]))
    r = client.get("/ping", headers={"Origin": origin})
    assert r.status_code == 200
    # An explicit allowlist reflects the origin and may enable credentials.
    assert r.headers["Access-Control-Allow-Origin"] == origin
    assert r.headers["Access-Control-Allow-Credentials"] == "true"
    # A disallowed origin is not echoed back.
    r2 = client.get("/ping", headers={"Origin": "https://evil.example"})
    assert r2.headers.get("Access-Control-Allow-Origin") != "https://evil.example"


def _app_with_error_handling() -> FastAPI:
    """Mirror create_app's error wiring: request-context (catches unhandled
    exceptions) inside CORS, plus the ProviderError -> 502 handler."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ProviderError)
    async def _provider_error(request: Request, exc: ProviderError) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc), "kind": exc.kind},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    @app.post("/boom")
    async def boom():
        raise ValueError("unexpected bug")

    @app.post("/provider-down")
    async def provider_down():
        raise ProviderError("Provider rejected the API key.", kind="auth")

    return app


def test_unhandled_exception_returns_500_with_cors_header():
    # The regression: an unhandled exception must come back as a JSON 500 that
    # still carries the CORS header, instead of a bare 500 the browser masks as
    # an opaque "No 'Access-Control-Allow-Origin' header" error.
    client = TestClient(_app_with_error_handling(), raise_server_exceptions=False)
    r = client.post("/boom", headers={"Origin": "https://abos-web.onrender.com"})
    assert r.status_code == 500
    assert r.json()["detail"] == "Internal Server Error"
    assert r.headers["Access-Control-Allow-Origin"] == "*"


def test_provider_error_returns_502_with_cors_header():
    client = TestClient(_app_with_error_handling(), raise_server_exceptions=False)
    r = client.post("/provider-down", headers={"Origin": "https://abos-web.onrender.com"})
    assert r.status_code == 502
    body = r.json()
    assert body["kind"] == "auth"
    assert "API key" in body["detail"]
    assert r.headers["Access-Control-Allow-Origin"] == "*"
