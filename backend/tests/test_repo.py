"""Bundle-backed repos (RFC 0003): the coding function's git repos as files on the
company store — no git server, no GitHub — and the bf_mcp tools a worker drives.
"""

from __future__ import annotations

import json

import pytest

from app.api import bf_mcp
from app.config import settings
from app.models import Company
from app.services import repo as repo_svc
from tests.conftest import requires_db
from tests.test_files_provider import FakeFileProvider


def test_name_validation_and_base64_roundtrip():
    assert repo_svc.normalize_name("product") == "product"
    assert repo_svc.normalize_name("product.bundle") == "product"  # suffix stripped
    for bad in ("", "../etc", "a/b", "x y", "a" * 65):
        with pytest.raises(repo_svc.RepoError):
            repo_svc.normalize_name(bad)
    raw = b"\x00git-bundle\xff binary"
    assert repo_svc.decode_bundle(repo_svc.encode_bundle(raw)) == raw
    with pytest.raises(repo_svc.RepoError):
        repo_svc.decode_bundle("not!base64!")


def test_size_guard(monkeypatch):
    monkeypatch.setattr(settings, "repo_max_bundle_bytes", 10)
    with pytest.raises(repo_svc.RepoError):
        repo_svc._check_size(b"12345678901")  # 11 > 10
    repo_svc._check_size(b"12345")  # under cap: fine


@requires_db
async def test_save_load_list_over_the_file_store(session_factory, company_with_budget):
    provider = FakeFileProvider()
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        # New repo: nothing there yet.
        assert await repo_svc.load_bundle(
            db, provider, company_id=company.id, repo="product") is None
        await repo_svc.save_bundle(
            db, provider, company=company, repo="product",
            content=b"BUNDLE-v1", head="main", note="init")
        await db.commit()

    async with session_factory() as db:
        got = await repo_svc.load_bundle(db, provider, company_id=company_with_budget, repo="product")
        assert got == b"BUNDLE-v1"
        repos = await repo_svc.list_repos(db, company_id=company_with_budget)
        assert repos and repos[0]["repo"] == "product" and repos[0]["head"] == "main"

    # Push overwrites in place (one canonical bundle; history lives inside it).
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        await repo_svc.save_bundle(
            db, provider, company=company, repo="product", content=b"BUNDLE-v2", head="main")
        await db.commit()
    async with session_factory() as db:
        assert await repo_svc.load_bundle(
            db, provider, company_id=company_with_budget, repo="product") == b"BUNDLE-v2"
        assert len(await repo_svc.list_repos(db, company_id=company_with_budget)) == 1


def _payload(rpc: dict) -> dict:
    return json.loads(rpc["result"]["content"][0]["text"])


@requires_db
async def test_repo_tools_over_mcp(session_factory, company_with_budget, monkeypatch):
    provider = FakeFileProvider()
    monkeypatch.setattr(
        "app.services.integrations.resolve_file_provider",
        lambda db, *, company_id: _return(provider),
    )
    cid = company_with_budget
    aid = None

    async with session_factory() as db:
        # get_repo on a fresh repo → exists false.
        r = await bf_mcp._call_tool(db, cid, aid, 1, {
            "name": "get_repo", "arguments": {"repo": "product"}})
        assert _payload(r) == {"repo": "product", "exists": False, "bundle_b64": ""}

    async with session_factory() as db:
        r = await bf_mcp._call_tool(db, cid, aid, 2, {"name": "push_repo", "arguments": {
            "repo": "product", "bundle_b64": repo_svc.encode_bundle(b"BUNDLE"),
            "head": "main", "diff": "+ hello", "summary": "first commit"}})
        assert _payload(r)["ok"] is True

    async with session_factory() as db:
        r = await bf_mcp._call_tool(db, cid, aid, 3, {
            "name": "get_repo", "arguments": {"repo": "product"}})
        body = _payload(r)
        assert body["exists"] is True
        assert repo_svc.decode_bundle(body["bundle_b64"]) == b"BUNDLE"

        r = await bf_mcp._call_tool(db, cid, aid, 4, {"name": "list_repos", "arguments": {}})
        assert _payload(r)["repos"][0]["repo"] == "product"

    # A bad repo name is a clean tool error, not a crash.
    async with session_factory() as db:
        r = await bf_mcp._call_tool(db, cid, aid, 5, {
            "name": "get_repo", "arguments": {"repo": "../secret"}})
        assert r["result"]["isError"] is True


async def _return(value):
    return value
