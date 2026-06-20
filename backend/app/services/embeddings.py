"""Embedding seam for Company Memory.

Memory recall ranks entries by vector similarity, so every memory needs an
embedding. Two embedders sit behind the :class:`Embedder` Protocol:

- :class:`HashingEmbedder` (default) — a dependency-free, deterministic
  feature-hashing embedder. It yields lexical (shared-token) cosine similarity,
  needs no API key, and works fully offline; good enough for MVP retrieval.
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
    failure or empty input, so memory writes/recall degrade gracefully."""
    if not text:
        return None
    embedder = get_embedder()
    aembed = getattr(embedder, "aembed", None)
    if aembed is not None:
        return await aembed(text)
    return embedder.embed(text)
