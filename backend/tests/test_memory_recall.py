"""Company Memory improvements — DB-free coverage.

Covers the real embeddings adapter (OpenAI REST response parsing), the async
embed dispatch, and the recency-decayed recall re-ranking.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import embeddings
from app.services.embeddings import (
    DIM,
    HashingEmbedder,
    LocalEmbedder,
    OpenAIEmbedder,
    _build_embedder,
    _to_dim,
)
from app.services.memory import _recency_weight, _rerank

# ─────────────────────────── OpenAI embedder (pure parser) ───────────────────────────


def test_openai_parse_response_success():
    vec = OpenAIEmbedder._parse_response(200, {"data": [{"embedding": [0.1] * DIM}]})
    assert vec is not None and len(vec) == DIM and vec[0] == pytest.approx(0.1)


def test_openai_parse_response_wrong_dim_is_rejected():
    assert OpenAIEmbedder._parse_response(200, {"data": [{"embedding": [0.1, 0.2]}]}) is None


def test_openai_parse_response_empty_data():
    assert OpenAIEmbedder._parse_response(200, {"data": []}) is None


def test_openai_parse_response_error_status():
    assert OpenAIEmbedder._parse_response(401, {"error": {"message": "bad key"}}) is None


def test_openai_embedder_sync_embed_is_none():
    # Network-bound: the synchronous path must not pretend to embed.
    assert OpenAIEmbedder(api_key="k").embed("hello") is None


@pytest.mark.asyncio
async def test_openai_aembed_without_key_returns_none():
    # No key configured -> no network call, graceful None.
    assert await OpenAIEmbedder(api_key="").aembed("hello") is None


# ─────────────────────────── async dispatch ───────────────────────────


@pytest.mark.asyncio
async def test_embed_text_uses_hashing_by_default(monkeypatch):
    monkeypatch.setattr(embeddings, "_embedder", HashingEmbedder())
    vec = await embeddings.embed_text("grow the sales pipeline")
    assert vec is not None and len(vec) == DIM


@pytest.mark.asyncio
async def test_embed_text_empty_is_none():
    assert await embeddings.embed_text("") is None
    assert await embeddings.embed_text(None) is None


@pytest.mark.asyncio
async def test_embed_text_prefers_async_embedder(monkeypatch):
    class _Async:
        dim = DIM

        def embed(self, text):  # sync path should be ignored
            return [9.0] * DIM

        async def aembed(self, text):
            return [1.0] * DIM

    monkeypatch.setattr(embeddings, "_embedder", _Async())
    vec = await embeddings.embed_text("x")
    assert vec[0] == 1.0  # came from aembed, not embed


@pytest.mark.asyncio
async def test_embed_text_caps_input_to_embedder(monkeypatch):
    """Oversized content is clipped to ``embeddings_max_input_chars`` before it
    reaches the embedder, so a real API's token limit can't drop the vector."""
    seen: dict = {}

    class _Recorder:
        dim = DIM

        def embed(self, text):
            seen["len"] = len(text)
            return [1.0] * DIM

    monkeypatch.setattr(embeddings, "_embedder", _Recorder())
    monkeypatch.setattr(embeddings.settings, "embeddings_max_input_chars", 100)
    await embeddings.embed_text("a" * 5000)
    assert seen["len"] == 100


@pytest.mark.asyncio
async def test_embed_text_cap_disabled_passes_full_text(monkeypatch):
    seen: dict = {}

    class _Recorder:
        dim = DIM

        def embed(self, text):
            seen["len"] = len(text)
            return [1.0] * DIM

    monkeypatch.setattr(embeddings, "_embedder", _Recorder())
    monkeypatch.setattr(embeddings.settings, "embeddings_max_input_chars", 0)
    await embeddings.embed_text("a" * 5000)
    assert seen["len"] == 5000


# ─────────────────────────── recency-decayed re-ranking ───────────────────────────


def _entry(days_old: float):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(created_at=now - timedelta(days=days_old))


def test_recency_weight_halves_each_half_life():
    now = datetime.now(timezone.utc)
    fresh = _recency_weight(now, now, 30)
    half = _recency_weight(now - timedelta(days=30), now, 30)
    quarter = _recency_weight(now - timedelta(days=60), now, 30)
    assert fresh == pytest.approx(1.0)
    assert half == pytest.approx(0.5, abs=1e-9)
    assert quarter == pytest.approx(0.25, abs=1e-9)


def test_recency_weight_disabled_when_half_life_nonpositive():
    now = datetime.now(timezone.utc)
    assert _recency_weight(now - timedelta(days=365), now, 0) == 1.0


def test_rerank_breaks_similarity_ties_by_recency():
    now = datetime.now(timezone.utc)
    old = _entry(120)
    new = _entry(1)
    # Same cosine distance (0.2) -> the fresher entry should rank first.
    ranked = _rerank([(old, 0.2), (new, 0.2)], now=now, half_life_days=30, limit=2)
    assert ranked == [new, old]


def test_rerank_prefers_closer_when_same_age():
    now = datetime.now(timezone.utc)
    a = _entry(5)
    b = _entry(5)
    ranked = _rerank([(a, 0.6), (b, 0.1)], now=now, half_life_days=30, limit=2)
    assert ranked == [b, a]  # smaller distance = more similar = first


def test_rerank_respects_limit():
    now = datetime.now(timezone.utc)
    scored = [(_entry(i), 0.1 * i) for i in range(1, 6)]
    assert len(_rerank(scored, now=now, half_life_days=30, limit=3)) == 3


# ─────────────────────────── local (fastembed) embedder ───────────────────────────


def test_to_dim_pads_short_vectors():
    out = _to_dim([0.5, 0.25], dim=4)
    assert out == [0.5, 0.25, 0.0, 0.0]


def test_to_dim_truncates_long_vectors():
    assert _to_dim([1, 2, 3, 4, 5], dim=3) == [1.0, 2.0, 3.0]


def test_to_dim_rejects_empty_or_bad():
    assert _to_dim([]) is None
    assert _to_dim([object()]) is None


def test_local_embedder_falls_back_to_hashing_when_unavailable():
    emb = LocalEmbedder()
    emb._unavailable = True  # simulate fastembed missing / model load failure
    vec = emb.embed("grow the sales pipeline")
    assert vec is not None and len(vec) == DIM  # hashing fallback, padded to the column


def test_local_embedder_uses_model_and_pads(monkeypatch):
    class _StubModel:
        def embed(self, texts):
            yield [0.5] * 384  # a 384-dim model vector

    emb = LocalEmbedder()
    monkeypatch.setattr(emb, "_model_or_none", lambda: _StubModel())
    vec = emb.embed("hello")
    assert len(vec) == DIM
    assert vec[0] == 0.5 and vec[383] == 0.5 and vec[384] == 0.0  # padded past 384


def test_local_embedder_empty_text_is_none():
    assert LocalEmbedder().embed("") is None


@pytest.mark.asyncio
async def test_local_embedder_aembed_offloads(monkeypatch):
    emb = LocalEmbedder()
    monkeypatch.setattr(emb, "_model_or_none", lambda: None)  # -> hashing fallback
    vec = await emb.aembed("customer acquisition cost")
    assert vec is not None and len(vec) == DIM


def test_build_embedder_dispatches_to_local(monkeypatch):
    monkeypatch.setattr(embeddings.settings, "embeddings_provider", "local")
    assert isinstance(_build_embedder(), LocalEmbedder)


def test_build_embedder_default_is_local(monkeypatch):
    # The shipped default selects the local neural embedder.
    monkeypatch.setattr(embeddings.settings, "embeddings_provider", "local")
    assert isinstance(_build_embedder(), LocalEmbedder)
