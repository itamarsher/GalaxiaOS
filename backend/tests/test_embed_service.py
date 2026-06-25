"""Remote embedder + standalone embedding service (the off-API ONNX host).

Covers the ``RemoteEmbedder`` client (URL normalization, graceful degradation,
response mapping) and the ``app.embed_service`` FastAPI contract including the
shared-secret gate. The local fastembed model is never loaded here — the service's
embedder is monkeypatched — so these stay fast and DB-free.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import embeddings
from app.services.embeddings import DIM, RemoteEmbedder, _build_embedder, _to_dim

# ─────────────────────────── RemoteEmbedder (client) ───────────────────────────


def test_build_embedder_selects_remote(monkeypatch):
    monkeypatch.setattr(embeddings.settings, "embeddings_provider", "remote")
    assert isinstance(_build_embedder(), RemoteEmbedder)


def test_remote_url_gets_https_scheme_and_trim():
    # Render's `property: host` is a bare host — assume https, drop trailing slash.
    assert RemoteEmbedder("abos-embeddings.onrender.com")._base_url == (
        "https://abos-embeddings.onrender.com"
    )
    assert RemoteEmbedder("http://localhost:9000/")._base_url == "http://localhost:9000"


def test_remote_sync_embed_is_none():
    # Network-bound: the synchronous path must not pretend to embed.
    assert RemoteEmbedder("http://x").embed("hello") is None


@pytest.mark.asyncio
async def test_remote_aembed_without_url_returns_none():
    assert await RemoteEmbedder("").aembed("hello") is None


@pytest.mark.asyncio
async def test_remote_aembed_empty_text_returns_none():
    assert await RemoteEmbedder("http://x").aembed("   ") is None


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.content = b"x"

    def json(self):
        return self._payload


class _FakeClient:
    """Minimal stand-in for httpx.AsyncClient used as an async context manager."""

    response: _FakeResponse | None = None
    last_post: dict | None = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeClient.last_post = {"url": url, "json": json, "headers": headers or {}}
        return _FakeClient.response


@pytest.mark.asyncio
async def test_remote_aembed_maps_vector_and_sends_secret(monkeypatch):
    import httpx

    _FakeClient.response = _FakeResponse(200, {"embedding": [0.5] * 384, "dim": DIM})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    vec = await RemoteEmbedder("http://embed", secret="s3cret").aembed("hello")
    assert vec is not None and len(vec) == DIM  # 384-dim padded to 1536
    assert vec == _to_dim([0.5] * 384)
    assert _FakeClient.last_post["url"] == "http://embed/embed"
    assert _FakeClient.last_post["headers"].get("x-embeddings-secret") == "s3cret"


@pytest.mark.asyncio
async def test_remote_aembed_http_error_status_returns_none(monkeypatch):
    import httpx

    _FakeClient.response = _FakeResponse(503, {})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    assert await RemoteEmbedder("http://embed").aembed("hello") is None


@pytest.mark.asyncio
async def test_remote_aembed_bad_body_returns_none(monkeypatch):
    import httpx

    _FakeClient.response = _FakeResponse(200, {"embedding": "not-a-list"})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    assert await RemoteEmbedder("http://embed").aembed("hello") is None


# ─────────────────────────── embed_service (server) ───────────────────────────


def _client(monkeypatch, *, secret: str = "", vector=None):
    from app import embed_service

    class _Emb:
        async def aembed(self, text):
            return vector

    monkeypatch.setattr(embed_service, "_embedder", _Emb())
    monkeypatch.setattr(embed_service.settings, "embeddings_remote_secret", secret)
    return TestClient(embed_service.app)


def test_embed_service_health(monkeypatch):
    resp = _client(monkeypatch).get("/health")
    assert resp.status_code == 200 and resp.json()["status"] == "ok"


def test_embed_service_returns_vector(monkeypatch):
    client = _client(monkeypatch, vector=[0.25] * DIM)
    resp = client.post("/embed", json={"text": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dim"] == DIM and body["embedding"][0] == pytest.approx(0.25)


def test_embed_service_empty_vector_is_null(monkeypatch):
    client = _client(monkeypatch, vector=None)
    resp = client.post("/embed", json={"text": ""})
    assert resp.status_code == 200 and resp.json()["embedding"] is None


def test_embed_service_secret_required_when_configured(monkeypatch):
    client = _client(monkeypatch, secret="topsecret", vector=[0.1] * DIM)
    # Missing / wrong secret -> 401.
    assert client.post("/embed", json={"text": "x"}).status_code == 401
    assert (
        client.post(
            "/embed", json={"text": "x"}, headers={"x-embeddings-secret": "nope"}
        ).status_code
        == 401
    )
    # Correct secret -> ok.
    ok = client.post("/embed", json={"text": "x"}, headers={"x-embeddings-secret": "topsecret"})
    assert ok.status_code == 200
