"""Render observability: client parsing + credential scoping.

The client is exercised offline with a mock transport; the resolver test proves
the global (dogfooding-account) key is offered ONLY to Galaxia, while any company
can use its own BYOK render key.
"""

from __future__ import annotations

import base64
import os

import httpx
import pytest

from app.config import settings
from app.integrations.render import RenderClient, RenderError
from app.runtime.tools.render_ops import _resolve_client
from app.services import apikeys, galaxia
from tests.conftest import requires_db


def _client(handler) -> RenderClient:
    return RenderClient(api_key="rnd_x", transport=httpx.MockTransport(handler))


def _set_master_key() -> None:
    settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


# ── client parsing (offline) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_services_parses_wrapped_rows():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/services")
        return httpx.Response(
            200,
            json=[
                {"service": {"id": "srv-1", "name": "abos-api", "type": "web_service",
                             "dashboardUrl": "https://dash", "suspended": "not_suspended"}}
            ],
        )

    services = await _client(handler).list_services()
    assert len(services) == 1
    assert services[0].id == "srv-1" and services[0].name == "abos-api"


@pytest.mark.asyncio
async def test_list_and_get_deploys_parse():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/deploys"):
            return httpx.Response(
                200,
                json=[{"deploy": {"id": "dep-1", "status": "live",
                                  "commit": {"id": "abcdef1234567", "message": "fix  the   thing"},
                                  "createdAt": "t1", "finishedAt": "t2"}}],
            )
        return httpx.Response(
            200,
            json={"id": "dep-1", "status": "build_failed", "commit": {"id": "z9", "message": "m"}},
        )

    deploys = await _client(handler).list_deploys("srv-1")
    assert deploys[0].status == "live"
    assert deploys[0].commit_id == "abcdef123456"  # clipped to 12
    assert deploys[0].commit_message == "fix the thing"  # whitespace collapsed

    d = await _client(handler).get_deploy("srv-1", "dep-1")
    assert d.status == "build_failed"


@pytest.mark.asyncio
async def test_get_logs_parses_and_collapses_whitespace():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/logs")
        assert req.url.params.get("ownerId") == "own-1"
        assert req.url.params.get("resource") == "srv-1"
        return httpx.Response(
            200,
            json={"logs": [{"timestamp": "t1", "message": "line   one"},
                           {"timestamp": "t2", "message": "boom"}], "hasMore": False},
        )

    client = RenderClient(api_key="k", owner_id="own-1", transport=httpx.MockTransport(handler))
    logs = await client.get_logs("srv-1")
    assert [ln.message for ln in logs] == ["line one", "boom"]


@pytest.mark.asyncio
async def test_get_logs_requires_owner_id():
    client = RenderClient(
        api_key="k", owner_id="", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    with pytest.raises(RenderError) as exc:
        await client.get_logs("srv-1")
    assert "owner id" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_missing_key_raises():
    with pytest.raises(RenderError):
        await RenderClient(api_key="").list_services()


@pytest.mark.asyncio
async def test_401_is_explained():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "bad"})

    with pytest.raises(RenderError) as exc:
        await _client(handler).list_services()
    assert "401" in str(exc.value)


# ── credential scoping (global key is Galaxia-only) ───────────────────────────


@requires_db
async def test_byok_render_key_resolves_for_any_company(
    session_factory, company_with_budget, monkeypatch
):
    _set_master_key()
    monkeypatch.setattr(settings, "render_api_key", "")  # no global key
    async with session_factory() as db:
        assert await _resolve_client(db, company_with_budget) is None  # no key, not galaxia
        await apikeys.store_key(
            db, company_id=company_with_budget, provider="render", plaintext="rnd_byok"
        )
        await db.commit()
    async with session_factory() as db:
        assert await _resolve_client(db, company_with_budget) is not None


@requires_db
async def test_global_key_is_offered_only_to_galaxia(
    session_factory, company_with_budget, monkeypatch
):
    monkeypatch.setattr(settings, "render_api_key", "global-dogfooding-key")
    async with session_factory() as db:
        # A tenant company with no BYOK key does NOT get our global account.
        assert await _resolve_client(db, company_with_budget) is None
        await galaxia._run(db)
        await db.commit()
    async with session_factory() as db:
        # Galaxia gets the global client.
        assert await _resolve_client(db, galaxia.galaxia_company_id()) is not None
