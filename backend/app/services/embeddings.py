"""Embedding seam for Company Memory.

Memory recall ranks entries by vector similarity, so every memory needs an
embedding. Two embedders sit behind the :class:`Embedder` Protocol:

- :class:`HashingEmbedder` (default) — a dependency-free, deterministic
  feature-hashing embedder. It yields lexical (shared-token) cosine similarity,
  needs no API key, and works fully offline; good enough for MVP retrieval.
- :class:`LocalEmbedder` — a real neural model run locally via ``fastembed``
  (ONNX/CPU, ``ABOS_EMBEDDINGS_PROVIDER=local``). No per-call cost and no network
  once the model is cached. ``fastembed`` is an optional dependency (the
  ``local-embeddings`` extra); if it isn't installed or the model can't load, this
  degrades to the hashing embedder so memory never breaks. Model output (e.g. a
  384-dim bge-small vector) is zero-padded to the 1536-dim column, which preserves
  cosine similarity.
- :class:`OpenAIEmbedder` — a real semantic model via the OpenAI embeddings REST
  API (``ABOS_EMBEDDINGS_PROVIDER=openai`` + ``ABOS_OPENAI_API_KEY``). Called over
  ``httpx`` (not the ``openai`` SDK, which is fenced to ``app/providers``) and
  pinned to the 1536-dim pgvector column via the API's ``dimensions`` parameter.

Callers use :func:`embed_text` (async): it dispatches to whichever embedder is
configured and **never raises** — any failure (no key, network, bad response)
returns ``None`` so the write simply stores no vector and recall falls back to
recency. Switching providers only re-embeds *new* writes; mixing vector spaces is
why a backfill is needed when changing it on a populated database.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
from typing import Protocol, runtime_checkable

from app.config import settings

DIM = 1536
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_OPENAI_ENDPOINT = "https://api.openai.com/v1/embeddings"
_log = logging.getLogger("app.embeddings")


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float] | None:
        """Synchronous embed (offline embedders). Async embedders return ``None``
        here and implement :meth:`aembed` instead — use :func:`embed_text`."""
        ...


class HashingEmbedder(Embedder):
    """Signed feature hashing into a fixed-dim, L2-normalised vector."""

    dim = DIM

    def embed(self, text: str) -> list[float] | None:
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return None
        vec = [0.0] * self.dim
        for tok in tokens:
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
            idx = h % self.dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return None
        return [v / norm for v in vec]


def _to_dim(vec, dim: int = DIM) -> list[float] | None:
    """Coerce a model vector to exactly ``dim`` floats: zero-pad if shorter,
    truncate if longer. Zero-padding is cosine-preserving (the extra dims are 0 in
    both query and stored vectors), so a 384-dim model fits the 1536-dim column."""
    try:
        values = [float(x) for x in vec]
    except (TypeError, ValueError):
        return None
    if not values:
        return None
    if len(values) >= dim:
        return values[:dim]
    return values + [0.0] * (dim - len(values))


class LocalEmbedder(Embedder):
    """Local neural embeddings via fastembed (ONNX/CPU) — no cost, offline once cached.

    fastembed is an optional dependency and the model loads lazily on first use. If
    it isn't installed or the model can't load/run, every call falls back to the
    hashing embedder so Company Memory keeps working. The model's native dimension
    is padded/truncated to the 1536-dim pgvector column by :func:`_to_dim`.
    """

    dim = DIM

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or settings.local_embeddings_model
        self._model = None
        self._unavailable = False
        self._fallback = HashingEmbedder()

    def _model_or_none(self):
        if self._model is None and not self._unavailable:
            try:
                from fastembed import TextEmbedding

                kwargs = {}
                cache_dir = (settings.local_embeddings_cache_dir or "").strip()
                if cache_dir:
                    kwargs["cache_dir"] = cache_dir
                self._model = TextEmbedding(model_name=self._model_name, **kwargs)
            except Exception as exc:  # noqa: BLE001 — import/download/load all degrade the same way
                self._unavailable = True
                _log.warning(
                    "local embedder unavailable (%s); falling back to the hashing embedder. "
                    "Install the 'local-embeddings' extra to enable it.",
                    exc,
                )
        return self._model

    def embed(self, text: str) -> list[float] | None:
        text = (text or "").strip()
        if not text:
            return None
        model = self._model_or_none()
        if model is None:
            return self._fallback.embed(text)
        try:
            vec = next(iter(model.embed([text])))
        except Exception as exc:  # noqa: BLE001 — never let an embed failure break a write/recall
            _log.warning("local embedding failed (%s); using hashing fallback", exc)
            return self._fallback.embed(text)
        return _to_dim(vec)

    async def aembed(self, text: str) -> list[float] | None:
        # fastembed inference is CPU-bound; run it off the event loop.
        return await asyncio.to_thread(self.embed, text)


class OpenAIEmbedder(Embedder):
    """Real semantic embeddings via the OpenAI REST API (credential-gated)."""

    dim = DIM

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.openai_api_key
        self._model = model or settings.embeddings_model
        self._timeout = timeout if timeout is not None else settings.embeddings_timeout_seconds

    def embed(self, text: str) -> list[float] | None:
        # Network-bound: no synchronous path. Callers go through ``embed_text``.
        return None

    async def aembed(self, text: str) -> list[float] | None:
        text = (text or "").strip()
        if not text or not self._api_key:
            return None
        import httpx

        payload = {"model": self._model, "input": text, "dimensions": DIM}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    _OPENAI_ENDPOINT,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                data = resp.json() if resp.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            _log.warning("OpenAI embedding request failed: %s", exc)
            return None
        vec = self._parse_response(resp.status_code, data)
        if vec is None:
            _log.warning("OpenAI embedding response unusable (HTTP %s)", resp.status_code)
        return vec

    @staticmethod
    def _parse_response(status_code: int, body: dict) -> list[float] | None:
        """Map ``{"data": [{"embedding": [...]}]}`` to a 1536-dim vector, or ``None``."""
        if status_code >= 400:
            return None
        data = body.get("data") or []
        if not data:
            return None
        vec = data[0].get("embedding")
        if not isinstance(vec, list) or len(vec) != DIM:
            return None
        try:
            return [float(x) for x in vec]
        except (TypeError, ValueError):
            return None


def _build_embedder() -> Embedder:
    provider = (settings.embeddings_provider or "hashing").strip().lower()
    if provider in ("", "hashing", "simulated"):
        return HashingEmbedder()
    if provider in ("local", "fastembed"):
        return LocalEmbedder()
    if provider == "openai":
        return OpenAIEmbedder()
    raise ValueError(f"unknown embeddings provider: {provider!r}")


_embedder: Embedder = _build_embedder()


def get_embedder() -> Embedder:
    return _embedder


def embed(text: str) -> list[float] | None:
    """Synchronous embed — offline embedders only (kept for back-compat/tests).

    Returns ``None`` for async (network) embedders; use :func:`embed_text` instead.
    """
    return get_embedder().embed(text)


async def embed_text(text: str | None) -> list[float] | None:
    """Embed ``text`` with the configured embedder. Never raises; ``None`` on any
    failure or empty input, so memory writes/recall degrade gracefully.

    The input is capped to ``embeddings_max_input_chars`` first. This is the one
    place a length bound belongs: real embedding APIs (e.g. OpenAI's) reject input
    over a fixed token limit, so an oversized memory would otherwise embed to
    nothing and become recall-invisible. Callers therefore store the *full* content
    and let this seam bound only what gets embedded — the title + opening carry the
    semantic signal, so a clipped embedding still retrieves well."""
    if not text:
        return None
    limit = settings.embeddings_max_input_chars
    if limit and len(text) > limit:
        text = text[:limit]
    embedder = get_embedder()
    aembed = getattr(embedder, "aembed", None)
    if aembed is not None:
        return await aembed(text)
    return embedder.embed(text)
