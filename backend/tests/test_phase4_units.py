"""Pure-function tests for Phase 4: reputation math and embeddings."""

from __future__ import annotations

import math

from app.services import embeddings
from app.services.reputation import _running_mean


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_running_mean_converges():
    # First sample sets the value; repeated samples pull the mean toward them.
    v = _running_mean(0.5, 1.0, 0)  # n=0 -> takes the sample fully
    assert v == 1.0
    v2 = _running_mean(0.0, 1.0, 1)  # one prior sample
    assert v2 == 0.5


def test_embedding_is_deterministic_and_unit_norm():
    a = embeddings.embed("grow the sales pipeline with outbound email")
    b = embeddings.embed("grow the sales pipeline with outbound email")
    assert a == b
    assert math.isclose(_cosine(a, a), 1.0, rel_tol=1e-6)
    assert embeddings.embed("") is None


def test_embedding_similar_text_is_closer_than_disjoint():
    q = embeddings.embed("reduce customer acquisition cost")
    near = embeddings.embed("our customer acquisition cost is rising")
    far = embeddings.embed("the weather in tokyo is sunny today")
    assert _cosine(q, near) > _cosine(q, far)
