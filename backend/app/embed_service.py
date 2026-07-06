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

The model is warmed at startup and held for the process lifetime (the point of the
dedicated host). Crucially this service runs the embedder in **strict** mode (no
hashing fallback): if the ONNX model isn't ready — e.g. mid cold-start, or it
failed to load — ``/embed`` returns ``503`` rather than a hashing vector. That
keeps the pgvector column a single, coherent semantic space; the caller
(``RemoteEmbedder``) treats the 503 as a transient miss and simply stores no
vector, so recall falls back to recency instead of being poisoned by a
non-semantic vector that merely *looks* valid.
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.services.embeddings import DIM, LocalEmbedder

_log = logging.getLogger("app.embed_service")

# One process-lifetime embedder for this host — this *is* the resident model we
# moved off the API. ``allow_fallback=False`` means it never substitutes a hashing
# vector for a real one.
_embedder = LocalEmbedder(allow_fallback=False)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Warm the model at boot so the first request after a free-tier cold start gets
    # a real vector immediately, instead of racing the lazy load (and 503-ing).
    # Best-effort: if it can't load we still come up and return 503s — never
    # hashing — until it can.
    try:
        ready = await _to_thread_ready()
        _log.info("embed service startup: model_ready=%s", ready)
    except Exception:  # noqa: BLE001 — boot must not crash on a warmup hiccup
        _log.exception("embed service warmup failed")
    yield


async def _to_thread_ready() -> bool:
    import asyncio

    return await asyncio.to_thread(_embedder.is_ready)


app = FastAPI(title="ABOS Embeddings", version="0.1.0", lifespan=_lifespan)


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
    # Cheap liveness only — does not load the model (so a waking instance reports
    # healthy quickly). Use /ready to gate on the model actually being loaded.
    return {"status": "ok"}


@app.get("/ready", tags=["meta"])
async def ready() -> dict:
    if await _to_thread_ready():
        return {"status": "ready"}
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="model not loaded"
    )


@app.post("/embed", tags=["embeddings"])
async def embed(
    req: EmbedRequest,
    x_embeddings_secret: str | None = Header(default=None),
) -> dict:
    _check_secret(x_embeddings_secret)
    text = (req.text or "").strip()
    if not text:
        # Genuinely nothing to embed — an honest "no vector", not a failure.
        return {"embedding": None, "dim": DIM}
    vec = await _embedder.aembed(text)
    if vec is None:
        # Strict mode: a None here means the ONNX model isn't available (still
        # loading on a cold start, or it failed to load) — NEVER a hashing vector.
        # Signal a transient failure so the caller stores no vector rather than
        # ever persisting a non-semantic one into the shared vector space.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="embedder not ready",
        )
    return {"embedding": vec, "dim": DIM}
