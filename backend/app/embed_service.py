"""Standalone embedding microservice — the local fastembed/ONNX model on its own host.

On the 512MB free tier the API and its in-process worker share one memory budget,
and the local neural embedder's ONNX model (~150-200MB resident) is by far the
largest thing that would live there. This tiny FastAPI app runs that model in a
*separate* free service so the model sits in its own 512MB, while the API talks to
it over HTTP via :class:`app.services.embeddings.RemoteEmbedder`
(``ABOS_EMBEDDINGS_PROVIDER=remote``). Same Docker image as the API — only the
start command differs — so the model baked into the image at build time is reused.

Contract (mirrors what ``RemoteEmbedder`` expects):
- ``POST /embed`` ``{"text": "..."}`` → ``{"embedding": [float, ...], "dim": 1536}``.
- ``GET /health`` → ``{"status": "ok"}`` (cheap; does not load the model).
- A shared secret (``ABOS_EMBEDDINGS_REMOTE_SECRET``), when set, must be presented
  in the ``x-embeddings-secret`` header — free services are reachable on their
  public ``*.onrender.com`` URL, so this keeps the endpoint from being open.

The model loads lazily on the first ``/embed`` and is then held for the process
lifetime (the point of the dedicated host), degrading to the hashing embedder if
fastembed can't load — exactly as in-process ``local`` mode does.
"""

from __future__ import annotations

import hmac

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.services.embeddings import DIM, LocalEmbedder

# One process-lifetime embedder for this host — this *is* the resident model we
# moved off the API. Instantiation is cheap; the ONNX model loads on first embed.
_embedder = LocalEmbedder()

app = FastAPI(title="ABOS Embeddings", version="0.1.0")


class EmbedRequest(BaseModel):
    text: str


def _check_secret(provided: str | None) -> None:
    expected = settings.embeddings_remote_secret
    if not expected:
        return  # No secret configured (dev) — open, like the rest of local dev.
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad secret")


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.post("/embed", tags=["embeddings"])
async def embed(
    req: EmbedRequest,
    x_embeddings_secret: str | None = Header(default=None),
) -> dict:
    _check_secret(x_embeddings_secret)
    vec = await _embedder.aembed(req.text)
    if vec is None:
        # Empty input (or a degraded embedder that returned nothing) — surface an
        # honest "no vector" rather than a fabricated one; the caller stores none
        # and recall falls back to recency.
        return {"embedding": None, "dim": DIM}
    return {"embedding": vec, "dim": DIM}
