"""Structured logging, request-id propagation, and an access-log middleware."""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import sys
import time
import traceback
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

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


#: Loggers we must never escalate — the escalation path itself and its
#: dependencies — or a failure while reporting an error would report itself.
_ESCALATION_SKIP_PREFIXES = ("abos.error_monitor", "abos.events", "httpx", "httpcore")


class ErrorEscalationHandler(logging.Handler):
    """Forward every ``ERROR``+ log record carrying a traceback to the error monitor.

    This is the single, system-wide capture point for code errors: because the
    request-500 handler, the worker loop, and the cron jobs all log their failures
    with ``exc_info`` through the standard logging tree, attaching this one handler
    to the root logger escalates all of them without touching each call site.

    Emission is fire-and-forget on the running event loop and fully guarded, so it
    never blocks or breaks the logging call. When no loop is running (a purely
    synchronous context) it simply skips — the API and worker both run under a loop.
    """

    def __init__(self, level: int = logging.ERROR) -> None:
        super().__init__(level=level)

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            if record.levelno < logging.ERROR or not record.exc_info:
                return
            if record.name.startswith(_ESCALATION_SKIP_PREFIXES):
                return
            exc_type, exc_value, _tb = record.exc_info
            if exc_type is None:
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return  # no event loop; escalation is best-effort
            error_type = getattr(exc_type, "__name__", str(exc_type))
            message = str(exc_value) if exc_value else record.getMessage()
            tb_text = "".join(traceback.format_exception(exc_type, exc_value, _tb))
            context = dict(getattr(record, "extra_fields", None) or {})
            context.setdefault("event", record.getMessage())
            from app.services import error_monitor

            loop.create_task(
                error_monitor.report_code_error(
                    error_type=error_type,
                    message=message,
                    where=record.name,
                    traceback_text=tb_text,
                    context=context,
                )
            )
        except Exception:  # noqa: BLE001 — a logging handler must never raise
            pass


def configure_logging(
    level: str = "INFO", json_logs: bool = True, escalate_errors: bool = False
) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    handlers: list[logging.Handler] = [handler]
    if escalate_errors:
        handlers.append(ErrorEscalationHandler())
    root = logging.getLogger()
    root.handlers = handlers
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
        except Exception as exc:
            # Convert an otherwise-unhandled exception into a JSON 500 *here*,
            # inside the CORS middleware, so the response still carries the
            # Access-Control-* headers. If we re-raised, Starlette's outermost
            # error handler (which sits outside CORS) would return a bare 500
            # with no CORS headers, and the browser would mask the real failure
            # as an opaque "No 'Access-Control-Allow-Origin' header" error. The
            # full traceback is logged below; the body exposes only the
            # exception *type* (never the message/traceback) plus the request id,
            # so a failure can be diagnosed from the response without leaking
            # internals or needing log access.
            _log.exception(
                "request_error",
                extra={"extra_fields": {"method": request.method, "path": request.url.path}},
            )
            return JSONResponse(
                {
                    "detail": "Internal Server Error",
                    "error": type(exc).__name__,
                    "request_id": rid,
                },
                status_code=500,
                headers={"X-Request-ID": rid},
            )
        finally:
            request_id_var.reset(token)
