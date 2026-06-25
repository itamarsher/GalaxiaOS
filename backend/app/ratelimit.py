"""Fixed-window rate limiting (in-memory default, Redis for multi-process).

Keyed by authenticated user when a valid bearer token is present, else client IP.
Health/docs endpoints are exempt. Over-limit requests get ``429`` with a
``Retry-After`` header.
"""

from __future__ import annotations

import time
from typing import Protocol

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.security import decode_access_token

_EXEMPT_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json")


class RateLimiterBackend(Protocol):
    async def allow(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds) for one hit on ``key``."""
        ...


class InMemoryRateLimiter:
    """Per-key fixed-window counter for a single process / tests.

    ``clock`` is injectable so the window-reset behaviour is unit-testable
    without sleeping.
    """

    def __init__(self, limit: int, window_seconds: int, clock=time.monotonic):
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._state: dict[str, tuple[float, int]] = {}  # key -> (window_start, count)
        self._last_sweep = clock()

    async def allow(self, key: str) -> tuple[bool, int]:
        now = self._clock()
        self._maybe_sweep(now)
        window_start, count = self._state.get(key, (now, 0))
        if now - window_start >= self._window:
            window_start, count = now, 0
        count += 1
        self._state[key] = (window_start, count)
        if count > self._limit:
            retry_after = max(1, int(self._window - (now - window_start)))
            return False, retry_after
        return True, 0

    def _maybe_sweep(self, now: float) -> None:
        """Drop keys whose window has elapsed so ``_state`` can't grow unbounded.

        Without this, every distinct client (user id or IP) leaves a permanent
        entry behind — a slow leak that matters most on the single free-tier
        instance, which uses this in-memory backend. We only sweep once per
        window so the common per-request path stays O(1).
        """
        if now - self._last_sweep < self._window:
            return
        self._last_sweep = now
        cutoff = now - self._window
        stale = [k for k, (start, _) in self._state.items() if start <= cutoff]
        for k in stale:
            del self._state[k]


class RedisRateLimiter:
    """Fixed-window counter in Redis (INCR + EXPIRE) for multi-process deploys."""

    def __init__(self, redis, limit: int, window_seconds: int):
        self._redis = redis
        self._limit = limit
        self._window = window_seconds

    async def allow(self, key: str) -> tuple[bool, int]:
        redis_key = f"ratelimit:{key}:{int(time.time()) // self._window}"
        count = await self._redis.incr(redis_key)
        if count == 1:
            await self._redis.expire(redis_key, self._window)
        if count > self._limit:
            ttl = await self._redis.ttl(redis_key)
            return False, max(1, ttl)
        return True, 0


def build_limiter() -> RateLimiterBackend:
    window = 60
    if settings.rate_limit_backend == "redis":
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        return RedisRateLimiter(client, settings.rate_limit_per_minute, window)
    return InMemoryRateLimiter(settings.rate_limit_per_minute, window)


def _client_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        user_id = decode_access_token(auth[7:])
        if user_id is not None:
            return f"user:{user_id}"
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiterBackend):
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)
        allowed, retry_after = await self._limiter.allow(_client_key(request))
        if not allowed:
            return JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
