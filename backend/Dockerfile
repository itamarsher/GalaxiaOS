FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Bake the local-embeddings (fastembed) model into the image at build time so
    # it is never downloaded over the network at runtime. The runtime embedder
    # reads the same path (app.config.local_embeddings_cache_dir).
    ABOS_LOCAL_EMBEDDINGS_CACHE_DIR=/app/.fastembed_cache

WORKDIR /app

# uv for fast installs; libgomp1 is onnxruntime's runtime dependency (fastembed),
# without which the local embedder would fall back to hashing.
RUN pip install uv \
    && apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN uv pip install --system -e .

COPY . .

# Pre-download + warm the local embeddings model into the image (same model and
# cache dir as the runtime embedder). Running a real embed also fails the build
# loudly if onnxruntime can't execute, rather than silently degrading later.
RUN python -c "from app.config import settings; from fastembed import TextEmbedding; list(TextEmbedding(model_name=settings.local_embeddings_model, cache_dir=settings.local_embeddings_cache_dir or None).embed(['warmup']))"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
