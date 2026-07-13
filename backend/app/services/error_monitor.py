"""System-wide error monitoring → deduplicated auto-fix tracker issues.

Two sources of production errors are escalated to GitHub issues that the Claude
Code auto-fix pipeline (issue-triage → issue-implement → CI → auto-merge) can pick
up:

1. **Code errors** — any exception logged with a traceback anywhere in the API or
   worker. :class:`app.observability.ErrorEscalationHandler` forwards those log
   records here, so the request-500 handler, cron jobs, and the worker loop are all
   covered without per-call-site wiring.
2. **Render platform errors** — a cron calls :func:`scan_render_platform`, which
   uses the read-only Render API client to spot failed deploys and suspended
   services and files an issue for each.

Everything is best-effort and heavily deduplicated so a hot error path can't spam
the tracker: an in-process TTL cache collapses repeats of the same *fingerprint*
within ``error_monitor_cooldown_minutes``, and the tracker itself dedupes by title
(posting a "+1" demand comment on an existing open issue instead of a duplicate).
The whole module is a no-op unless ``ABOS_ERROR_MONITOR_ENABLED`` is set and an
issue tracker is configured, so it costs nothing in local/dev.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict

from app.config import settings
from app.integrations.issues import IssueTrackerError, get_issue_tracker
from app.integrations.render import RenderError, get_render_client
from app.observability import get_logger

_log = get_logger("abos.error_monitor")

# fingerprint -> monotonic timestamp of last report, for the cooldown window.
_recent: OrderedDict[str, float] = OrderedDict()

# Render deploy statuses that mean the deploy did not go live.
_RENDER_FAILED_STATUSES = {
    "build_failed",
    "update_failed",
    "pre_deploy_failed",
    "canceled",
    "deactivated",
}

# Volatile substrings (ids, addresses, hex blobs, line/col numbers) are stripped
# from a message before fingerprinting so the "same" error collapses to one issue.
_VOLATILE = re.compile(
    r"0x[0-9a-fA-F]+"
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"  # uuid
    r"|\b\d+\b"
)


def _labels() -> list[str]:
    return [s.strip() for s in settings.error_monitor_labels.split(",") if s.strip()]


def _normalize(text: str) -> str:
    return _VOLATILE.sub("#", text or "").strip()


def _fingerprint(*parts: str) -> str:
    joined = "|".join(_normalize(p) for p in parts if p)
    return hashlib.sha1(joined.encode("utf-8", "replace")).hexdigest()[:16]


def _seen_recently(fingerprint: str) -> bool:
    """Return True if this fingerprint was reported within the cooldown window.

    Also records/refreshes the fingerprint's timestamp and prunes the cache. Not
    reported recently → records it and returns False (caller should file).
    """
    now = time.monotonic()
    cooldown = max(0, settings.error_monitor_cooldown_minutes) * 60
    last = _recent.get(fingerprint)
    if last is not None and (now - last) < cooldown:
        return True
    _recent[fingerprint] = now
    _recent.move_to_end(fingerprint)
    # Evict oldest beyond the cap, and drop entries past the cooldown.
    while len(_recent) > max(1, settings.error_monitor_cache_size):
        _recent.popitem(last=False)
    return False


def reset_dedup_cache() -> None:
    """Test hook: forget every remembered fingerprint."""
    _recent.clear()


async def report_code_error(
    *,
    error_type: str,
    message: str,
    where: str,
    traceback_text: str | None = None,
    context: dict | None = None,
) -> bool:
    """Escalate a code error to a deduplicated tracker issue. Returns True if filed.

    ``where`` is the origin (a logger name, e.g. ``abos.access``); ``context`` adds
    request/task metadata to the issue body. No-op (returns False) when disabled,
    when no tracker is configured, or when the same fingerprint was seen recently.
    """
    if not settings.error_monitor_enabled:
        return False
    tracker = get_issue_tracker()
    if tracker is None:
        return False

    fingerprint = _fingerprint("code", where, error_type, message)
    if _seen_recently(fingerprint):
        return False

    title = f"[auto] {error_type} in {where}"
    body = _code_issue_body(
        error_type=error_type,
        message=message,
        where=where,
        traceback_text=traceback_text,
        context=context,
        fingerprint=fingerprint,
    )
    return await _file(title=title, body=body)


async def scan_render_platform() -> dict:
    """Scan our own Render services/deploys and file an issue per failure.

    Read-only: lists services, and for each inspects its most recent deploys plus
    its suspended flag. Failed deploys and suspended services each become a
    deduplicated issue. No-op when disabled, when no Render key is set, or when no
    tracker is configured.
    """
    result = {"services": 0, "issues_filed": 0, "skipped": None}
    if not (settings.error_monitor_enabled and settings.render_monitor_enabled):
        result["skipped"] = "disabled"
        return result
    client = get_render_client()
    if client is None:
        result["skipped"] = "no_render_key"
        return result
    if get_issue_tracker() is None:
        result["skipped"] = "no_tracker"
        return result

    try:
        services = await client.list_services(limit=50)
    except RenderError as exc:
        _log.warning("render_scan_list_failed", extra={"extra_fields": {"error": str(exc)}})
        return result

    filed = 0
    for svc in services:
        result["services"] += 1
        if str(svc.suspended).lower() == "suspended":
            if await _file_render_suspended(svc):
                filed += 1
        try:
            deploys = await client.list_deploys(
                svc.id, limit=max(1, settings.render_monitor_deploy_lookback)
            )
        except RenderError as exc:
            _log.warning(
                "render_scan_deploys_failed",
                extra={"extra_fields": {"service": svc.name, "error": str(exc)}},
            )
            continue
        # Only the most recent deploy reflects current health; older failures that
        # were superseded by a live deploy are not actionable.
        if deploys and deploys[0].status in _RENDER_FAILED_STATUSES:
            if await _file_render_deploy_failure(svc, deploys[0]):
                filed += 1

    result["issues_filed"] = filed
    return result


async def _file_render_suspended(svc) -> bool:
    fingerprint = _fingerprint("render-suspended", svc.id)
    if _seen_recently(fingerprint):
        return False
    title = f"[auto] Render service suspended: {svc.name}"
    body = (
        f"Render reports service **{svc.name}** (`{svc.type}`) is **suspended**, so "
        "it is not serving traffic.\n\n"
        f"- Service id: `{svc.id}`\n"
        f"- Dashboard: {svc.dashboard_url or '(n/a)'}\n\n"
        "Investigate why the service is suspended (billing, manual suspension, or a "
        "crash loop) and restore it.\n\n"
        f"<sub>fingerprint: `{fingerprint}` · filed automatically by the error monitor</sub>"
    )
    return await _file(title=title, body=body)


async def _file_render_deploy_failure(svc, deploy) -> bool:
    fingerprint = _fingerprint("render-deploy", svc.id, deploy.status)
    if _seen_recently(fingerprint):
        return False
    title = f"[auto] Render deploy failed on {svc.name} ({deploy.status})"
    body = (
        f"The latest Render deploy for **{svc.name}** (`{svc.type}`) ended in "
        f"**{deploy.status}**.\n\n"
        f"- Service id: `{svc.id}`\n"
        f"- Deploy id: `{deploy.id}`\n"
        f"- Commit: `{deploy.commit_id}` — {deploy.commit_message or '(no message)'}\n"
        f"- Finished: {deploy.finished_at or '(unknown)'}\n"
        f"- Dashboard: {svc.dashboard_url or '(n/a)'}\n\n"
        "Inspect the build/deploy logs for this service, find the cause of the "
        "failure, and fix it so the next deploy goes live.\n\n"
        f"<sub>fingerprint: `{fingerprint}` · filed automatically by the error monitor</sub>"
    )
    return await _file(title=title, body=body)


def _code_issue_body(
    *,
    error_type: str,
    message: str,
    where: str,
    traceback_text: str | None,
    context: dict | None,
    fingerprint: str,
) -> str:
    lines = [
        "An error was captured automatically in production and escalated for a fix.",
        "",
        f"- **Type:** `{error_type}`",
        f"- **Origin:** `{where}`",
    ]
    if message:
        lines.append(f"- **Message:** {message[:500]}")
    if context:
        for key, value in context.items():
            lines.append(f"- **{key}:** {str(value)[:200]}")
    if traceback_text:
        clipped = traceback_text[-4000:]
        lines += ["", "<details><summary>Traceback</summary>", "", "```", clipped, "```", "</details>"]
    lines += [
        "",
        f"<sub>fingerprint: `{fingerprint}` · filed automatically by the error monitor</sub>",
    ]
    return "\n".join(lines)


async def _file(*, title: str, body: str) -> bool:
    """File (or +1) a tracker issue. Best-effort: never raises to the caller."""
    tracker = get_issue_tracker()
    if tracker is None:
        return False
    try:
        res = await tracker.report_issue(title=title, body=body, labels=_labels() or None)
    except IssueTrackerError as exc:
        _log.warning("error_monitor_file_failed", extra={"extra_fields": {"error": str(exc)}})
        return False
    except Exception:  # noqa: BLE001 — escalation must never crash the caller
        _log.exception("error_monitor_file_crashed")
        return False
    _log.info(
        "error_monitor_issue",
        extra={"extra_fields": {"number": res.number, "created": res.created, "url": res.url}},
    )
    return res.created
