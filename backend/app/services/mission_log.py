"""Ephemeral live mission log — the fleet's latest milestone updates.

Agents narrate significant milestones ("started outreach", "landed 3 leads",
"drafting the investor update") as they execute; those beats are surfaced live on
the game dashboard's Mission Log table. They are deliberately **ephemeral** — a
capped, self-expiring Redis ring per company, never written to Postgres — so the
log is a live pulse of what's happening right now, not durable history (the
durable trail is tasks, memory, reports, and the comms index).

Redis (not in-process memory) is the store because the writer (the ``arq``
worker running the agent loop) and the reader (the API's SSE endpoint) are
usually separate processes; the same Redis they already share for the queue
carries these updates across that boundary. Every operation is best-effort: a
Redis hiccup must never fail an agent's tool call or break the event stream, so
writes swallow-and-log and reads degrade to an empty list.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis

from app.config import settings
from app.observability import get_logger

_log = get_logger("abos.mission_log")

# Lazily-built, process-local client (the worker and the API each hold their own,
# both pointed at the same Redis server). Overridable in tests.
_client: aioredis.Redis | None = None


def _redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


def _key(company_id: uuid.UUID | str) -> str:
    return f"abos:missionlog:{company_id}"


def _clip(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def record(
    company_id: uuid.UUID | str,
    *,
    agent_id: uuid.UUID | str | None,
    agent_name: str,
    role: str | None,
    headline: str,
    detail: str | None = None,
    kind: str = "update",
) -> dict | None:
    """Push one milestone update onto the company's live mission log.

    ``kind`` distinguishes an automatic milestone ``start`` (an agent picked up a
    task) from an agent-authored ``update``. Keeps only the most recent
    ``mission_log_max_entries`` and re-arms the key's TTL, so the ring both self-
    trims and self-expires. Best-effort: returns the stored entry, or ``None`` if
    the headline was empty or Redis was unreachable.
    """
    clipped = _clip(headline, settings.mission_log_headline_max_chars)
    if clipped is None:
        return None
    entry = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(UTC).isoformat(),
        "agent_id": str(agent_id) if agent_id is not None else None,
        "agent_name": agent_name,
        "role": role,
        "kind": kind,
        "headline": clipped,
        "detail": _clip(detail, settings.mission_log_detail_max_chars),
    }
    try:
        key = _key(company_id)
        pipe = _redis().pipeline()
        pipe.lpush(key, json.dumps(entry, separators=(",", ":")))
        pipe.ltrim(key, 0, settings.mission_log_max_entries - 1)
        pipe.expire(key, settings.mission_log_ttl_seconds)
        await pipe.execute()
    except Exception:  # noqa: BLE001 — never let a log update break the caller.
        _log.warning("mission_log_record_failed", extra={"extra_fields": {"company_id": str(company_id)}})
        return None
    return entry


async def recent(company_id: uuid.UUID | str, *, limit: int | None = None) -> list[dict]:
    """Return the most recent updates, newest first (best-effort; ``[]`` on error)."""
    count = limit or settings.mission_log_max_entries
    try:
        raw = await _redis().lrange(_key(company_id), 0, count - 1)
    except Exception:  # noqa: BLE001 — a dead Redis must not break the event stream.
        _log.warning("mission_log_read_failed", extra={"extra_fields": {"company_id": str(company_id)}})
        return []
    out: list[dict] = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except (ValueError, TypeError):
            continue
    return out
