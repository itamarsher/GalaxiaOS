"""The secret store + broker.

A **secret** is any sensitive value the company needs an agent to *use* but must
never *see*: a third-party API key, a password, a token. The design keeps three
promises:

1. **Encrypted at rest.** Values are sealed with the same envelope scheme as BYOK
   provider keys (a per-record data key wrapped under the app master key). Plaintext
   never touches the database.

2. **Never leaked to agents or memory.** Agents can't read a secret's value. They
   reference it by name as a ``{{secret:name}}`` placeholder in a tool argument; the
   *broker* (:func:`resolve_placeholders`) substitutes the real value only into the
   outbound request, at the network boundary, on a copy the transcript never sees.
   :func:`redact_text` is the belt-and-suspenders pass wired into the memory / chat /
   mission-log sinks so a value can't survive even if one slips through.

3. **Requestable by anyone.** An agent that hits a missing secret calls
   ``request_secret`` (raising a ``secret_request`` decision); the founder fulfils it
   through a dedicated secure endpoint — the value is sealed on arrival and never
   echoed into the decision note, DM, or payload.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import envelope
from app.models import Secret
from app.models.enums import SecretStatus

#: ``{{secret:name}}`` — the placeholder agents put in a tool argument to have the
#: broker splice in a real value at the network boundary. Names are the same handle
#: characters we allow on storage (see :func:`normalize_name`).
PLACEHOLDER_RE = re.compile(r"\{\{\s*secret:([A-Za-z0-9_.-]{1,120})\s*\}\}")


def normalize_name(name: str) -> str:
    """Canonicalise a secret handle: trimmed, lower-cased, safe characters only."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "").strip()).strip("_")
    return cleaned.lower()[:120]


def _sealed(row: Secret) -> envelope.SealedSecret:
    return envelope.SealedSecret(
        ciphertext=row.encrypted_value,
        wrapped_data_key=row.encrypted_data_key,
        nonce=row.nonce,
    )


async def store_secret(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    name: str,
    plaintext: str,
    description: str | None = None,
    allowed_host: str | None = None,
    requested_by_agent_id: uuid.UUID | None = None,
) -> Secret:
    """Seal and persist a secret, revoking any existing active secret of the same name.

    Returns the row (fingerprint only is ever exposed). The plaintext is dropped the
    moment it is sealed here.
    """
    handle = normalize_name(name)
    if not handle:
        raise ValueError("secret name is empty after normalisation")
    if not plaintext:
        raise ValueError("secret value is empty")

    existing = await db.scalars(
        select(Secret).where(
            Secret.company_id == company_id,
            Secret.name == handle,
            Secret.status == SecretStatus.active,
        )
    )
    for old in existing:
        old.status = SecretStatus.revoked

    sealed = envelope.seal(plaintext)
    row = Secret(
        company_id=company_id,
        name=handle,
        description=(description or None),
        encrypted_value=sealed.ciphertext,
        encrypted_data_key=sealed.wrapped_data_key,
        nonce=sealed.nonce,
        fingerprint=envelope.fingerprint(plaintext),
        allowed_host=(allowed_host or None),
        requested_by_agent_id=requested_by_agent_id,
        status=SecretStatus.active,
    )
    db.add(row)
    await db.flush()
    return row


async def list_secrets(db: AsyncSession, *, company_id: uuid.UUID) -> list[Secret]:
    """Active secrets for a company (fingerprint-only display; no decryption)."""
    rows = await db.scalars(
        select(Secret)
        .where(Secret.company_id == company_id, Secret.status == SecretStatus.active)
        .order_by(Secret.name)
    )
    return list(rows)


async def has_secret(db: AsyncSession, *, company_id: uuid.UUID, name: str) -> bool:
    """True if the company has an active secret with this name (no decryption)."""
    row = await db.scalar(
        select(Secret.id).where(
            Secret.company_id == company_id,
            Secret.name == normalize_name(name),
            Secret.status == SecretStatus.active,
        )
    )
    return row is not None


async def revoke_secret(
    db: AsyncSession, *, company_id: uuid.UUID, secret_id: uuid.UUID
) -> bool:
    """Revoke a single active secret. Tenant-scoped; ``False`` if not found/active."""
    row = await db.scalar(
        select(Secret).where(
            Secret.id == secret_id,
            Secret.company_id == company_id,
            Secret.status == SecretStatus.active,
        )
    )
    if row is None:
        return False
    row.status = SecretStatus.revoked
    await db.flush()
    return True


async def _active_plaintexts(
    db: AsyncSession, *, company_id: uuid.UUID
) -> dict[str, str]:
    """Decrypt the company's active secrets to ``{name: plaintext}``.

    Internal to the broker/scrubber only — never expose the result. Callers gate on
    :func:`has_any` first so the common (no-secrets) path decrypts nothing.
    """
    rows = await db.scalars(
        select(Secret).where(
            Secret.company_id == company_id, Secret.status == SecretStatus.active
        )
    )
    out: dict[str, str] = {}
    for row in rows:
        try:
            out[row.name] = envelope.open_secret(_sealed(row))
        except Exception:  # noqa: BLE001 — a single unreadable secret must not break the batch
            continue
    return out


async def has_any(db: AsyncSession, *, company_id: uuid.UUID) -> bool:
    """Cheap gate: does the company have *any* active secret? (No decryption.)"""
    row = await db.scalar(
        select(Secret.id).where(
            Secret.company_id == company_id, Secret.status == SecretStatus.active
        )
    )
    return row is not None


def _host_of(text: str) -> str | None:
    """Best-effort host extraction from an argument value that may be a URL."""
    m = re.search(r"https?://([^/\s:]+)", text or "")
    return m.group(1).lower() if m else None


def _first_host(node) -> str | None:
    """The first URL host found anywhere in an argument tree.

    Host-binding must be enforced against the request's destination, which usually
    lives in a ``url`` field *separate* from the header the secret sits in — so we
    derive one host for the whole call rather than per-string (where a bare header
    value has no URL and would slip past the check).
    """
    if isinstance(node, str):
        return _host_of(node)
    if isinstance(node, dict):
        for value in node.values():
            found = _first_host(value)
            if found:
                return found
    if isinstance(node, list):
        for value in node:
            found = _first_host(value)
            if found:
                return found
    return None


async def resolve_placeholders(
    db: AsyncSession, *, company_id: uuid.UUID, args: dict, host: str | None = None
) -> tuple[dict, set[str]]:
    """Return a deep copy of ``args`` with every ``{{secret:name}}`` substituted.

    This is the **broker**: it runs at the outbound-HTTP boundary on a *copy* so the
    real value only reaches the network, never the stored arguments or transcript.
    A secret bound to an ``allowed_host`` is spliced in only when the request targets
    that host (the host is taken from ``host`` or inferred from any URL in the args),
    so a leaked placeholder can't exfiltrate the value to an attacker's domain.

    Returns ``(substituted_args, used_names)``. Unknown or host-mismatched
    placeholders are left verbatim (the outbound call then simply carries the literal
    ``{{secret:...}}`` and fails visibly, rather than silently succeeding).
    """
    if not await has_any(db, company_id=company_id):
        return args, set()

    rows = {
        r.name: r
        for r in await db.scalars(
            select(Secret).where(
                Secret.company_id == company_id, Secret.status == SecretStatus.active
            )
        )
    }
    used: set[str] = set()
    # One destination host for the whole call (the URL usually lives in a different
    # field than the header the secret sits in).
    target = host or _first_host(args)

    def sub_str(value: str) -> str:
        def repl(m: re.Match) -> str:
            name = normalize_name(m.group(1))
            row = rows.get(name)
            if row is None:
                return m.group(0)
            # A host-bound secret is refused unless we can confirm the request targets
            # its host — including when no host is discernible at all (fail closed).
            if row.allowed_host and target != row.allowed_host.lower():
                return m.group(0)
            try:
                plaintext = envelope.open_secret(_sealed(row))
            except Exception:  # noqa: BLE001
                return m.group(0)
            used.add(name)
            return plaintext

        return PLACEHOLDER_RE.sub(repl, value)

    def walk(node):
        if isinstance(node, str):
            return sub_str(node)
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    return walk(args), used


async def fulfill_request(
    db: AsyncSession,
    *,
    decision,
    plaintext: str,
    user_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Fulfil an agent's ``secret_request`` decision by sealing the value + resuming.

    This is the value-safe cousin of :func:`app.services.decisions.resolve_decision`:
    it seals the founder's secret immediately and **never** writes it to a memory
    note, the decision payload, or the DM. The name / description / allowed_host the
    agent asked for live on the decision payload; the value arrives only here and
    only sealed. Returns the task id to resume (``None`` if nothing to resume).
    """
    from app.models import Task
    from app.models.enums import DecisionKind, DecisionStatus, TaskStatus
    from app.services import chat as chat_svc

    if decision.kind != DecisionKind.secret_request:
        raise ValueError("decision is not a secret_request")

    payload = decision.payload or {}
    name = normalize_name(str(payload.get("name") or ""))
    if not name:
        raise ValueError("secret_request decision has no name in its payload")

    await store_secret(
        db,
        company_id=decision.company_id,
        name=name,
        plaintext=plaintext,
        description=payload.get("reason") or payload.get("description"),
        allowed_host=payload.get("allowed_host"),
        requested_by_agent_id=decision.agent_id,
    )

    decision.status = DecisionStatus.approved
    decision.resolved_by_user_id = user_id
    decision.resolved_at = datetime.now(UTC)

    # Close the DM with a value-free acknowledgement.
    if decision.channel_id is not None:
        await chat_svc.post_system_reply(
            db,
            company_id=decision.company_id,
            channel_id=decision.channel_id,
            body=f"✅ Secret `{name}` provided and stored securely.",
        )

    if not decision.task_id:
        return None
    task = await db.get(Task, decision.task_id)
    if task is None or task.status not in (TaskStatus.waiting_approval, TaskStatus.running):
        return None
    task.status = TaskStatus.queued
    # A value-free resume directive: the agent learns the secret is now available and
    # to reference it by placeholder — never asking the founder to paste it in chat.
    task.input = {
        **(task.input or {}),
        "founder_ack": (
            f'The founder provided the secret you requested (`{name}`). It is stored '
            f"securely - use it by putting `{{{{secret:{name}}}}}` in the relevant tool "
            "argument (e.g. a request header or URL); it will be substituted at the "
            "network boundary. Never ask for or handle the raw value yourself. "
            + chat_svc.FOUNDER_ACK_DIRECTIVE
        ),
    }
    return task.id


async def redact_text(db: AsyncSession, *, company_id: uuid.UUID, text: str) -> str:
    """Replace any occurrence of an active secret's value with a safe marker.

    Defence-in-depth for the memory / chat / mission-log / observation sinks: even
    though the broker keeps plaintext out of agent-visible text by construction, this
    guarantees a value that slips in (e.g. a remote echoing it back, or a founder
    pasting it into a DM) never lands in durable storage. No-ops (and decrypts
    nothing) when the company has no active secrets.
    """
    if not text or not await has_any(db, company_id=company_id):
        return text
    values = await _active_plaintexts(db, company_id=company_id)
    redacted = text
    # Longest values first so a value that contains another is masked whole.
    for name, plaintext in sorted(values.items(), key=lambda kv: -len(kv[1])):
        if plaintext and plaintext in redacted:
            redacted = redacted.replace(plaintext, f"[redacted secret: {name}]")
    return redacted
