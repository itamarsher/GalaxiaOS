"""Structured logging, request-id propagation, and an access-log middleware."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Bound for the lifetime of a request; included in every log line emitted under it.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_log = logging.getLogger("abos.access")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id (honoring an inbound ``X-Request-ID``), binds it to a
    contextvar so all logs in the request carry it, and emits one access line."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.monotonic()
        try:
            response = await call_next(request)
            duration_ms = int((time.monotonic() - start) * 1000)
            response.headers["X-Request-ID"] = rid
            _log.info(
                "request",
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "ms": duration_ms,
                    }
                },
            )
            return response
        except Exception:
            _log.exception(
                "request_error",
                extra={"extra_fields": {"method": request.method, "path": request.url.path}},
            )
            raise
        finally:
            request_id_var.reset(token)
