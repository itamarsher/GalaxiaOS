"""Embedding seam for Company Memory.

Anthropic has no first-party embeddings API, so rather than couple memory to a
second vendor we default to a dependency-free, deterministic **feature-hashing**
embedder. It yields lexical (shared-token) cosine similarity — good enough for
MVP retrieval — behind an :class:`Embedder` Protocol so a real semantic model
(OpenAI/Voyage/local) can be swapped in without touching callers.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

DIM = 1536
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float] | None: ...


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


_embedder: Embedder = HashingEmbedder()


def get_embedder() -> Embedder:
    return _embedder


def embed(text: str) -> list[float] | None:
    return _embedder.embed(text)
