"""Reuse a founder's saved keys & connections when they launch a new business.

When someone creates their Nth company, the BYOK keys (Anthropic, Tavily, Resend,
…) and connections (Cloudflare, Google Drive, MCP servers) they already configured
on an earlier company are theirs — re-pasting the same secrets on every onboarding
is pure friction. This offers those credentials for one-click reuse.

Credentials are stored per company (envelope-encrypted under a per-record data
key), so "reuse" *copies* the secret into the new company: it is decrypted from the
source row and re-sealed for the target under a fresh data key (via
:func:`app.services.apikeys.store_key` / :func:`app.services.mcp.add_server`), never
shared by reference.

Reads run on a fresh, non-tenant-scoped session — the request session is RLS-pinned
to the target company and cannot see sibling rows — but are always scoped to the
SAME ``owner_user_id``, so this never reaches another founder's credentials. That is
the same guard :func:`app.services.integrations._owner_google_drive` relies on.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import envelope
from app.db import SessionLocal
from app.models import ApiKey, Company, McpServer
from app.models.enums import ApiKeyStatus
from app.services import apikeys
from app.services import mcp as mcp_svc

# Providers stored in ``api_keys`` that read as a linked external *connection*
# rather than a raw model/tool key; everything else is presented as a "key".
_CONNECTION_PROVIDERS = {"cloudflare", "google_drive"}

_KEY_LABELS = {
    "anthropic": "Anthropic (Claude) API key",
    "openai": "OpenAI API key",
    "tavily": "Tavily (web search) key",
    "resend": "Resend (email) key",
    "github": "GitHub token",
}
_CONNECTION_LABELS = {
    "cloudflare": "Cloudflare (websites & domains)",
    "google_drive": "Google Drive (file store)",
}


def _key_id(provider: str) -> str:
    return f"key:{provider}"


def _mcp_id(name: str) -> str:
    return f"mcp:{name}"


async def _gather(
    *, user_id: uuid.UUID, target_company_id: uuid.UUID
) -> tuple[dict[str, tuple[ApiKey, str]], dict[str, tuple[McpServer, str]]]:
    """Collect reusable keys and MCP connections from the user's *other* companies.

    Returns ``(keys, mcps)`` where ``keys`` maps a provider to its most-recent
    active key (with the source company name) and ``mcps`` maps a server slug to
    its most-recent server. Both are deduped so the founder is offered one entry
    per credential, and anything the *target* company already has is excluded.
    """
    async with SessionLocal() as s:
        # What the target already has, so we never offer to reuse a duplicate.
        have_providers = set(
            (
                await s.scalars(
                    select(ApiKey.provider).where(
                        ApiKey.company_id == target_company_id,
                        ApiKey.status == ApiKeyStatus.active,
                    )
                )
            ).all()
        )
        have_mcp = set(
            (
                await s.scalars(
                    select(McpServer.name).where(McpServer.company_id == target_company_id)
                )
            ).all()
        )

        key_rows = (
            await s.execute(
                select(ApiKey, Company.name)
                .join(Company, ApiKey.company_id == Company.id)
                .where(
                    Company.owner_user_id == user_id,
                    Company.id != target_company_id,
                    ApiKey.status == ApiKeyStatus.active,
                )
                .order_by(ApiKey.created_at.desc())
            )
        ).all()
        mcp_rows = (
            await s.execute(
                select(McpServer, Company.name)
                .join(Company, McpServer.company_id == Company.id)
                .where(
                    Company.owner_user_id == user_id,
                    Company.id != target_company_id,
                )
                .order_by(McpServer.created_at.desc())
            )
        ).all()

    # Rows arrive newest-first, so the first sighting of a provider/slug wins.
    keys: dict[str, tuple[ApiKey, str]] = {}
    for key, cname in key_rows:
        if key.provider in have_providers or key.provider in keys:
            continue
        keys[key.provider] = (key, cname)
    mcps: dict[str, tuple[McpServer, str]] = {}
    for server, cname in mcp_rows:
        if server.name in have_mcp or server.name in mcps:
            continue
        mcps[server.name] = (server, cname)
    return keys, mcps


async def list_reusable(
    *, user_id: uuid.UUID, target_company_id: uuid.UUID
) -> list[dict]:
    """Founder-facing catalog of credentials reusable into ``target_company_id``.

    Never returns a secret: keys carry only their display fingerprint, connections
    only a friendly label. Keys are listed before connections.
    """
    keys, mcps = await _gather(user_id=user_id, target_company_id=target_company_id)
    items: list[dict] = []
    for provider, (key, cname) in keys.items():
        is_conn = provider in _CONNECTION_PROVIDERS
        labels = _CONNECTION_LABELS if is_conn else _KEY_LABELS
        items.append(
            {
                "id": _key_id(provider),
                "kind": "connection" if is_conn else "key",
                "provider": provider,
                "label": labels.get(provider, provider),
                # A raw key shows its fingerprint; a connection's secret detail
                # (account id, refresh token) is never surfaced.
                "detail": None if is_conn else key.key_fingerprint,
                "source_company_id": key.company_id,
                "source_company_name": cname,
            }
        )
    for name, (server, cname) in mcps.items():
        count = len(server.tools_cache or [])
        items.append(
            {
                "id": _mcp_id(name),
                "kind": "connection",
                "provider": None,
                "label": server.label or name,
                "detail": f"{count} tool{'s' if count != 1 else ''}" if count else server.url,
                "source_company_id": server.company_id,
                "source_company_name": cname,
            }
        )
    # Keys first (so the essential Anthropic key leads), connections after.
    items.sort(key=lambda it: (it["kind"] == "connection", it["label"].lower()))
    return items


def _mcp_auth_token(server: McpServer) -> str | None:
    if not (server.encrypted_auth and server.encrypted_data_key and server.nonce):
        return None
    return envelope.open_secret(
        envelope.SealedSecret(
            ciphertext=server.encrypted_auth,
            wrapped_data_key=server.encrypted_data_key,
            nonce=server.nonce,
        )
    )


async def reuse(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    target_company_id: uuid.UUID,
    ids: list[str],
) -> list[str]:
    """Copy the selected reusable credentials into the target company.

    ``ids`` are the opaque ids from :func:`list_reusable`; anything not currently
    reusable for this user is ignored, so a client can never point reuse at a
    company it doesn't own. Returns the ids actually copied.
    """
    selected = set(ids)
    if not selected:
        return []
    keys, mcps = await _gather(user_id=user_id, target_company_id=target_company_id)
    copied: list[str] = []

    for provider, (key, _cname) in keys.items():
        if _key_id(provider) not in selected:
            continue
        plaintext = envelope.open_secret(
            envelope.SealedSecret(
                ciphertext=key.encrypted_key,
                wrapped_data_key=key.encrypted_data_key,
                nonce=key.nonce,
            )
        )
        await apikeys.store_key(
            db, company_id=target_company_id, provider=provider, plaintext=plaintext
        )
        copied.append(_key_id(provider))

    for name, (server, _cname) in mcps.items():
        if _mcp_id(name) not in selected:
            continue
        new_server = await mcp_svc.add_server(
            db,
            company_id=target_company_id,
            name=name,
            label=server.label,
            url=server.url,
            transport=server.transport,
            auth_token=_mcp_auth_token(server),
        )
        # Carry over the discovered tool cache so the reused server is usable
        # immediately, without waiting on a network refresh.
        new_server.tools_cache = server.tools_cache
        new_server.last_error = None
        copied.append(_mcp_id(name))

    await db.flush()
    return copied
