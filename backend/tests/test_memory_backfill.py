"""Backfill of null-embedding memories — DB-free coverage.

Exercises ``memory.backfill_embeddings`` with a fake session and a stubbed
embedder: the embedder probe gating, per-row UPDATE issuance, and the
skip-on-transient-miss path. No Postgres / pgvector needed.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Select, Update

from app.services import embeddings, memory
from app.services.embeddings import DIM


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    """Records UPDATE statements; returns preset rows for the one SELECT."""

    def __init__(self, rows):
        self._rows = rows
        self.updates = 0

    async def execute(self, stmt):
        if isinstance(stmt, Select):
            return _Result(self._rows)
        assert isinstance(stmt, Update)
        self.updates += 1
        return _Result([])


def _rows(n):
    return [(uuid.uuid4(), f"title {i}", f"content {i}") for i in range(n)]


@pytest.mark.asyncio
async def test_backfill_skips_when_embedder_not_ready(monkeypatch):
    # Probe returns None (embedder cold/down) -> don't touch the backlog at all.
    async def _none(text):
        return None

    monkeypatch.setattr(embeddings, "embed_text", _none)
    db = _FakeDB(_rows(5))
    res = await memory.backfill_embeddings(db, company_id=uuid.uuid4())
    assert res == {"scanned": 0, "updated": 0, "embedder_ready": False}
    assert db.updates == 0


@pytest.mark.asyncio
async def test_backfill_embeds_all_null_rows(monkeypatch):
    async def _vec(text):
        return [0.1] * DIM

    monkeypatch.setattr(embeddings, "embed_text", _vec)
    db = _FakeDB(_rows(4))
    res = await memory.backfill_embeddings(db, company_id=uuid.uuid4(), limit=10)
    assert res["scanned"] == 4 and res["updated"] == 4 and res["embedder_ready"] is True
    assert db.updates == 4


@pytest.mark.asyncio
async def test_backfill_skips_transient_row_miss(monkeypatch):
    # Probe ok, but one row transiently yields no vector -> skip it, keep going.
    async def _vec(text):
        return None if "content 2" in text else [0.2] * DIM

    monkeypatch.setattr(embeddings, "embed_text", _vec)
    db = _FakeDB(_rows(5))
    res = await memory.backfill_embeddings(db, company_id=uuid.uuid4(), limit=10)
    assert res["scanned"] == 5 and res["updated"] == 4  # row "content 2" skipped
    assert db.updates == 4


@pytest.mark.asyncio
async def test_backfill_no_null_rows_is_noop(monkeypatch):
    async def _vec(text):
        return [0.3] * DIM

    monkeypatch.setattr(embeddings, "embed_text", _vec)
    db = _FakeDB([])
    res = await memory.backfill_embeddings(db, company_id=uuid.uuid4())
    assert res == {"scanned": 0, "updated": 0, "embedder_ready": True}
    assert db.updates == 0
