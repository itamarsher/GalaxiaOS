"""The Founder MCP tool surface: a user's AI can create/read/steer its own companies,
resolve the gating decisions, and cannot touch companies it doesn't found.

Exercises the ``_call_tool`` dispatch directly against the fixture session (the JSON-RPC
transport is a thin wrapper that only adds token→user_id auth on top).
"""

from __future__ import annotations

import base64
import json
import os
import uuid

from sqlalchemy import select

from app.api import founder_mcp as fm
from app.config import settings
from app.models import (
    Agent,
    AgentRun,
    Company,
    DecisionRequest,
    Membership,
    Mission,
    Task,
    User,
)
from app.models.enums import (
    AgentRole,
    AgentStatus,
    CompanyStatus,
    DecisionKind,
    DecisionStatus,
    MembershipRole,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from tests.conftest import requires_db

pytestmark = requires_db


async def _active_company_with_founder(db):
    u = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(u)
    await db.flush()
    company = Company(owner_user_id=u.id, name="C", status=CompanyStatus.active)
    db.add(company)
    await db.flush()
    db.add(Membership(user_id=u.id, company_id=company.id, role=MembershipRole.founder))
    return u, company


def _payload(rpc: dict) -> dict:
    return json.loads(rpc["result"]["content"][0]["text"])


async def _user(db) -> uuid.UUID:
    u = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(u)
    await db.flush()
    return u.id


@requires_db
async def test_create_list_snapshot_and_playbook(session_factory):
    async with session_factory() as db:
        uid = await _user(db)
        await db.commit()

    # create_company
    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            1,
            {
                "name": "create_company",
                "arguments": {
                    "mission_text": "Sell handmade widgets online",
                    "budget_cents": 10000,
                },
            },
        )
        cid = _payload(r)["company_id"]
        assert _payload(r)["status"] == "draft"

    # list_companies shows it
    async with session_factory() as db:
        r = await fm._call_tool(db, uid, 2, {"name": "list_companies", "arguments": {}})
        assert any(c["id"] == cid for c in _payload(r)["companies"])

    # get_company_snapshot
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 3, {"name": "get_company_snapshot", "arguments": {"company_id": cid}}
        )
        snap = _payload(r)
        assert snap["company"]["status"] == "draft"
        assert snap["budget"]["limit_cents"] == 10000

    # set_playbook
    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            4,
            {
                "name": "set_playbook",
                "arguments": {"company_id": cid, "playbook": "Be bold and concise."},
            },
        )
        assert _payload(r)["customized"] is True
        got = await db.scalar(fm.select(Company).where(Company.id == uuid.UUID(cid)))
        assert got.playbook == "Be bold and concise."


@requires_db
async def test_edit_mission_resets_and_preserves_involvement(session_factory):
    """edit_mission changes the mission (back to draft) without dropping the gates."""
    async with session_factory() as db:
        uid = await _user(db)
        await db.commit()

    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 1,
            {
                "name": "create_company",
                "arguments": {
                    "mission_text": "Old mission: sell widgets",
                    "budget_cents": 10000,
                    "involvement": "Approve every plan, hire and spend before it proceeds.",
                },
            },
        )
        cid = _payload(r)["company_id"]

    # edit_mission → new mission, company reset to draft
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 2,
            {
                "name": "edit_mission",
                "arguments": {
                    "company_id": cid,
                    "mission_text": "New mission: agent spend guardrails",
                    "constraints": ["stay lean"],
                },
            },
        )
        assert _payload(r)["status"] == "draft"

    async with session_factory() as db:
        mission = await db.scalar(fm.select(Mission).where(Mission.company_id == uuid.UUID(cid)))
        assert mission.raw_text == "New mission: agent spend guardrails"
        assert mission.constraints == ["stay lean"]
        # The founder's involvement (the approval gate) survives the mission change.
        m = await db.scalar(
            fm.select(Membership).where(Membership.company_id == uuid.UUID(cid))
        )
        assert m.involvement == "Approve every plan, hire and spend before it proceeds."


@requires_db
async def test_setup_tools_arm_gates_key_and_comms(session_factory, monkeypatch):
    """The founder-AI setup surface: involvement, comms guardrail, BYOK key, storage status."""
    settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()

    # No Drive in tests; stub resolution so get_storage_status doesn't reach the
    # app-global session in the legacy owner-drive fallback.
    async def _no_provider(db, *, company_id):
        return None

    monkeypatch.setattr(fm.integrations_svc, "resolve_file_provider", _no_provider)
    async with session_factory() as db:
        uid = await _user(db)
        await db.commit()
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 1,
            {"name": "create_company",
             "arguments": {"mission_text": "Sell widgets to agents", "budget_cents": 5000}},
        )
        cid = _payload(r)["company_id"]

    # set_involvement arms the gate (writes the founder membership's involvement)
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 2,
            {"name": "set_involvement",
             "arguments": {"company_id": cid, "involvement": "Approve every plan, hire, and spend."}},
        )
        assert _payload(r)["gates_armed"] is True
        m = await db.scalar(fm.select(Membership).where(Membership.company_id == uuid.UUID(cid)))
        assert m.involvement == "Approve every plan, hire, and spend."

    # set_comms_approval flips the guardrail
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 3,
            {"name": "set_comms_approval", "arguments": {"company_id": cid, "enabled": True}},
        )
        assert _payload(r)["external_comms_approval"] is True

    # add_provider_key stores it encrypted, returns only a fingerprint
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 4,
            {"name": "add_provider_key",
             "arguments": {"company_id": cid, "provider": "Anthropic", "api_key": "sk-secret-xyz"}},
        )
        p = _payload(r)
        assert p["provider"] == "anthropic" and p["status"] == "active"
        assert "sk-secret-xyz" not in json.dumps(p)  # plaintext never returned

    # get_storage_status: no Drive in tests → does not resolve, offers a connect hint
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 5, {"name": "get_storage_status", "arguments": {"company_id": cid}}
        )
        s = _payload(r)
        assert s["storage_resolves"] is False and s["connect_hint"]


@requires_db
async def test_connect_storage_over_mcp(session_factory, monkeypatch):
    """connect_storage verifies a Drive refresh token and stores it, so an agent can
    satisfy the launch storage prerequisite without an in-app OAuth redirect."""
    settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    settings.google_oauth_client_id = "cid"
    settings.google_oauth_client_secret = "csecret"

    verified: list = []

    async def _verify_ok(*, client_id, client_secret, refresh_token, root_folder_id="root"):
        verified.append((refresh_token, root_folder_id))

    monkeypatch.setattr(fm.integrations_svc, "verify_google_drive", _verify_ok)

    async with session_factory() as db:
        uid = await _user(db)
        await db.commit()
    async with session_factory() as db:
        cid = _payload(
            await fm._call_tool(
                db, uid, 1,
                {"name": "create_company",
                 "arguments": {"mission_text": "Maintain OSS forks", "budget_cents": 5000}},
            )
        )["company_id"]

    # Missing token → clean arg error, nothing stored.
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 2, {"name": "connect_storage", "arguments": {"company_id": cid}}
        )
        assert "error" in r

    # Happy path: token verified + stored (encrypted), only a boolean returned.
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 3,
            {"name": "connect_storage",
             "arguments": {"company_id": cid, "refresh_token": "rt-secret", "root_folder_id": "fld1"}},
        )
        p = _payload(r)
        assert p["connected"] is True and p["storage_resolves"] is True
        assert "rt-secret" not in json.dumps(p)  # token never echoed
    assert verified == [("rt-secret", "fld1")]  # it was actually verified before storing

    async with session_factory() as db:
        bundle = await fm.integrations_svc.get_google_drive(db, company_id=uuid.UUID(cid))
        assert bundle and bundle["refresh_token"] == "rt-secret"
        assert bundle["root_folder_id"] == "fld1"

    # A rejected token surfaces as a JSON-RPC error, not a 500.
    async def _verify_bad(*, client_id, client_secret, refresh_token, root_folder_id="root"):
        raise fm.FileProviderError("bad token")

    monkeypatch.setattr(fm.integrations_svc, "verify_google_drive", _verify_bad)
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 4,
            {"name": "connect_storage",
             "arguments": {"company_id": cid, "refresh_token": "nope"}},
        )
        assert "error" in r and "rejected" in r["error"]["message"]


def test_connect_discovery_doc_lists_bootstrap_and_tools():
    doc = fm._connect_doc()
    names = {t["name"] for t in doc["tools"]}
    assert {"create_company", "generate_org", "launch_company"} <= names
    assert len(doc["bootstrap"]) == 4
    assert "/auth/signup" in doc["paste_to_agent"]
    assert "/founder/connection" in doc["paste_to_agent"]
    assert doc["mcp_url"].endswith("/connect/founder")


class _StubReq:
    def __init__(self, body, auth=""):
        self.headers = {"Authorization": auth} if auth else {}
        self._body = body

    async def json(self):
        return self._body


async def test_introspection_token_optional_but_calls_require_token():
    """An agent can initialize + list tools with no token to discover the surface;
    every tools/call still needs a valid founder token."""
    # tools/list with no token → returns the catalog
    r = await fm.founder_mcp(_StubReq({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), None)
    assert any(t["name"] == "create_company" for t in r["result"]["tools"])
    # initialize with no token → serverInfo
    r = await fm.founder_mcp(_StubReq({"jsonrpc": "2.0", "id": 2, "method": "initialize"}), None)
    assert r["result"]["serverInfo"]["name"] == "abos-founder"
    # tools/call with no token → guided error pointing at the recipe, not a 500
    r = await fm.founder_mcp(
        _StubReq(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "list_companies", "arguments": {}}}
        ),
        None,
    )
    assert r["error"]["code"] == -32001 and "/connect" in r["error"]["message"]


@requires_db
async def test_get_decision_and_artifacts_over_mcp(session_factory):
    """Founder can read a decision's FULL body + payload and agent-produced artifacts —
    the content review path that list_decisions (truncated) can't serve."""
    from app.services import artifacts as artifacts_svc

    big = "OUTBOUND EMAIL DRAFT. " * 60  # > 600 chars, so truncation would hide the tail
    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        agent = Agent(company_id=company.id, role=AgentRole.ceo, name="CEO")
        db.add(agent)
        await db.flush()
        decision = DecisionRequest(
            company_id=company.id,
            agent_id=agent.id,
            kind=DecisionKind.plan_approval,
            summary=big,
            payload={"to": "cto@acme.com", "email_body": "Hi — fork toil…"},
            status=DecisionStatus.pending,
        )
        db.add(decision)
        art = await artifacts_svc.create_artifact(
            db,
            company_id=company.id,
            kind="one_pager",
            title="ForkFlow positioning",
            body_md="# ForkFlow AI\n\nThe full one-pager body.",
            source_agent_id=agent.id,
        )
        await db.commit()
        uid, cid, did, aid = u.id, str(company.id), str(decision.id), str(art.id)

    # get_decision: full (untruncated) summary + structured payload
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 1, {"name": "get_decision", "arguments": {"company_id": cid, "decision_id": did}}
        )
        p = _payload(r)
        assert len(p["summary"]) == len(big)  # not truncated to 600
        assert p["payload"]["to"] == "cto@acme.com"

    # list_artifacts + read_artifact
    async with session_factory() as db:
        r = await fm._call_tool(db, uid, 2, {"name": "list_artifacts", "arguments": {"company_id": cid}})
        assert any(a["id"] == aid and a["title"] == "ForkFlow positioning"
                   for a in _payload(r)["artifacts"])
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 3, {"name": "read_artifact", "arguments": {"company_id": cid, "artifact_id": aid}}
        )
        assert _payload(r)["body_md"].startswith("# ForkFlow AI")


@requires_db
async def test_list_and_read_files_over_mcp(session_factory, monkeypatch):
    """Founder can list and read the documents agents save to the file store —
    e.g. a drafted outreach sequence saved as a CompanyFile in the managed store."""
    from app.models import CompanyFile
    from app.models.enums import FileCategory

    class _StubProvider:
        async def download_file(self, file_id):
            assert file_id == "r2-key-1"
            return b"# ForkFlow outreach\n\nEmail 1 body..."

    async def _stub_provider(db, *, company_id):
        return _StubProvider()

    monkeypatch.setattr(fm.integrations_svc, "resolve_file_provider", _stub_provider)

    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        db.add(
            CompanyFile(
                company_id=company.id,
                category=FileCategory.artifact,
                name="ForkFlow_AI_Outbound_Pilot_Outreach_Sequence.md",
                mime_type="text/markdown",
                folder_path=".galaxia/ForkFlow AI/Artifacts",
                provider="r2",
                external_id="r2-key-1",
                size_bytes=42,
            )
        )
        await db.commit()
        uid, cid = u.id, str(company.id)

    async with session_factory() as db:
        r = await fm._call_tool(db, uid, 1, {"name": "list_files", "arguments": {"company_id": cid}})
        assert any(f["name"].startswith("ForkFlow_AI_Outbound") for f in _payload(r)["files"])

    # read_file by name → full decoded content from the provider
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 2,
            {"name": "read_file",
             "arguments": {"company_id": cid,
                           "name": "ForkFlow_AI_Outbound_Pilot_Outreach_Sequence.md"}},
        )
        p = _payload(r)
        assert p["encoding"] == "utf-8" and p["content"].startswith("# ForkFlow outreach")


def test_default_playbook_forbids_fabrication_and_premature_selling():
    from app.runtime.prompts import DEFAULT_COMPANY_PLAYBOOK

    p = DEFAULT_COMPANY_PLAYBOOK.lower()
    assert "fabricate" in p  # anti-fabrication rule present
    assert "pilot" in p and "mvp" in p  # no-sell-before-MVP rule
    assert "inbound" in p  # inbound/product-led preference
    # verified-over-described: code isn't an MVP until it's been executed/run
    assert "executed" in p and "request_capability" in p


def test_connect_doc_explains_verified_over_described_principle():
    """The agentic self-onboarding surfaces the 'code isn't real until run' concept,
    so an agent bootstrapping a company inherits it before it ships anything."""
    doc = fm._connect_doc()
    principle = doc["operating_principle"].lower()
    assert "executed" in principle
    assert "not an mvp" in principle
    assert "write_file" in doc["paste_to_agent"]
    assert any(t["name"] == "write_file" for t in doc["tools"])


@requires_db
async def test_reset_company_over_mcp_threads_delete_files(session_factory, monkeypatch):
    """The reset_company MCP tool resets the company and passes delete_files through."""
    captured = {}

    async def _fake_reset(db, *, company, mission_text=None, constraints=None, delete_files=False):
        captured["delete_files"] = delete_files
        company.status = CompanyStatus.draft
        return company

    monkeypatch.setattr(fm.company_reset_svc, "reset_company", _fake_reset)

    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        await db.commit()
        uid, cid = u.id, str(company.id)

    # delete_files=True is threaded through and reflected in the result.
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 1,
            {"name": "reset_company", "arguments": {"company_id": cid, "delete_files": True}},
        )
        p = _payload(r)
        assert p["status"] == "draft" and p["deleted_files"] is True
    assert captured["delete_files"] is True

    # Default (omitted) is False — a reset keeps files unless asked to purge.
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 2, {"name": "reset_company", "arguments": {"company_id": cid}}
        )
        assert _payload(r)["deleted_files"] is False
    assert captured["delete_files"] is False


@requires_db
async def test_set_budget_raises_the_cap(session_factory):
    """A founder can top up a company's monthly budget cap so a low-runway fleet keeps running."""
    from app.models import Budget
    from app.models.enums import BudgetPeriod

    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        db.add(Budget(company_id=company.id, period=BudgetPeriod.monthly,
                      limit_cents=30_000, spent_cents=29_500))
        await db.commit()
        uid, cid = u.id, str(company.id)

    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 1,
            {"name": "set_budget", "arguments": {"company_id": cid, "limit_cents": 60_000}},
        )
        p = _payload(r)
        assert p["limit_cents"] == 60_000
        assert p["available_cents"] == 60_000 - 29_500  # room restored

    async with session_factory() as db:
        b = await db.scalar(select(Budget).where(Budget.company_id == uuid.UUID(cid)))
        assert b.limit_cents == 60_000

    # Can't set the cap below what's already spent.
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 2,
            {"name": "set_budget", "arguments": {"company_id": cid, "limit_cents": 100}},
        )
        assert "error" in r and "below already-spent" in r["error"]["message"]


@requires_db
async def test_connect_function_delegates_to_external_and_mints_token(session_factory, monkeypatch):
    """connect_function flips a function to the external backend and mints a
    Business-Function connection token so a coding runtime can pull its work."""
    from app.models import Agent
    from app.models.enums import AgentBackendType, AgentRole
    from app.services import function_token

    monkeypatch.setattr(settings, "function_connection_secret", "test-secret")
    monkeypatch.setattr(settings, "public_api_base_url", "https://api.example")

    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        eng = Agent(
            company_id=company.id, role=AgentRole.custom, name="Engineering",
            config={"function": "engineering"}, backend_type=AgentBackendType.native,
        )
        db.add(eng)
        await db.flush()
        await db.commit()
        uid, cid, eid = u.id, str(company.id), eng.id

    # Identify the function by its catalog key.
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 1,
            {"name": "connect_function", "arguments": {"company_id": cid, "function": "engineering"}},
        )
        p = _payload(r)
        assert p["backend_type"] == "external"
        assert p["mcp_url"].endswith("/connect/business-function")
        # The minted token verifies back to exactly this (company, function).
        assert function_token.verify(p["token"]) == (uuid.UUID(cid), eid)

    # The agent was actually flipped to the external (pull) backend and marked
    # pull-staffed so it takes precedence over any global push Gateway.
    async with session_factory() as db:
        row = await db.get(Agent, eid)
        assert row.backend_type is AgentBackendType.external
        assert (row.config or {}).get("worker") == "pull"
        assert (row.config or {}).get("function") == "engineering"  # existing config preserved


@requires_db
async def test_write_file_over_mcp(session_factory, monkeypatch):
    """Founder can seed a knowledge bundle into the company's file store: write_file
    archives it (provider upload + CompanyFile row) so agents can read it back."""
    from app.integrations.files import FolderRef, StoredFile
    from app.models import CompanyFile
    from app.models.enums import FileCategory

    uploaded: dict = {}

    class _StubProvider:
        async def ensure_folder(self, path):
            return FolderRef(folder_id="fld-1", path="/".join(path))

        async def upload_file(self, *, folder_id, name, content, mime_type):
            uploaded["name"] = name
            uploaded["content"] = content
            return StoredFile(
                file_id="key-1", name=name, mime_type=mime_type, size_bytes=len(content)
            )

    async def _stub_provider(db, *, company_id):
        return _StubProvider()

    monkeypatch.setattr(fm.integrations_svc, "resolve_file_provider", _stub_provider)

    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        await db.commit()
        uid, cid = u.id, str(company.id)

    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            1,
            {
                "name": "write_file",
                "arguments": {
                    "company_id": cid,
                    "name": "ForkFlow_Lessons",
                    "content": "# Verified over described\n\nRun the code.",
                    "description": "root-cause bundle",
                },
            },
        )
        p = _payload(r)
        assert p["category"] == "knowledge"  # default folder
        assert p["name"].endswith(".md")  # extension inferred
        assert p["size_bytes"] > 0

    assert uploaded["content"] == b"# Verified over described\n\nRun the code."

    # The bundle is now listable/readable like any filed document.
    async with session_factory() as db:
        row = await db.scalar(
            select(CompanyFile).where(CompanyFile.company_id == uuid.UUID(cid))
        )
        assert row is not None and row.category is FileCategory.knowledge
        assert row.description == "root-cause bundle"


@requires_db
async def test_delete_file_over_mcp(session_factory, monkeypatch):
    """delete_file removes the tracking row and best-effort deletes the blob."""
    from app.models import CompanyFile
    from app.models.enums import FileCategory
    from app.services import files as files_mod

    deleted_keys: list = []

    class _StubProvider:
        async def delete_file(self, file_id):
            deleted_keys.append(file_id)

    async def _stub(db, *, company_id):
        return _StubProvider()

    monkeypatch.setattr(files_mod, "resolve_file_provider", _stub)

    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        f = CompanyFile(
            company_id=company.id,
            category=FileCategory.artifact,
            name="dup.md",
            mime_type="text/markdown",
            folder_path=".galaxia/x",
            provider="r2",
            external_id="k1",
            size_bytes=1,
        )
        db.add(f)
        await db.flush()
        await db.commit()
        uid, cid, fid = u.id, str(company.id), str(f.id)

    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 1, {"name": "delete_file", "arguments": {"company_id": cid, "file_id": fid}}
        )
        assert _payload(r)["deleted"] is True

    async with session_factory() as db:
        assert await db.get(CompanyFile, uuid.UUID(fid)) is None  # row gone
    assert deleted_keys == ["k1"]  # blob delete attempted


@requires_db
async def test_function_health_and_retarget_over_mcp(session_factory):
    from app.services import function_catalog as fc
    from app.services import function_health as fh
    from app.services.onboarding import provision_fleet

    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        db.add(Mission(company_id=company.id, raw_text="m"))
        await db.flush()
        await provision_fleet(db, company=company,
                              specs=fc.resolve_selection(["website"]), total_budget_cents=10_000)
        await fh.sync_health_krs(db, company=company)
        await db.commit()
        uid, cid = u.id, str(company.id)

    # get_function_health surfaces the seeded KPIs.
    async with session_factory() as db:
        r = await fm._call_tool(db, uid, 1, {
            "name": "get_function_health", "arguments": {"company_id": cid}})
        board = _payload(r)
        assert any(f["function"] == "website" for f in board["functions"])
        assert {k["metric"] for k in board["agent_kpis"]}  # agent KPIs present

    # set_health_target retargets a KPI; the improvement cycle now measures off it.
    async with session_factory() as db:
        r = await fm._call_tool(db, uid, 2, {
            "name": "set_health_target",
            "arguments": {"company_id": cid, "metric": "signup_conversion_rate", "target": 0.09}})
        assert _payload(r)["target"] == 0.09

    async with session_factory() as db:
        targets = await fh.kr_targets(db, company_id=uuid.UUID(cid))
        assert targets["signup_conversion_rate"] == 0.09

    # An unknown KPI is a clean JSON-RPC error, not a 500.
    async with session_factory() as db:
        r = await fm._call_tool(db, uid, 3, {
            "name": "set_health_target",
            "arguments": {"company_id": cid, "metric": "bogus", "target": 1}})
        assert "error" in r


async def test_cannot_touch_a_company_you_dont_found(session_factory):
    async with session_factory() as db:
        owner = await _user(db)
        other = await _user(db)
        await db.commit()
    async with session_factory() as db:
        cid = _payload(
            await fm._call_tool(
                db,
                owner,
                1,
                {
                    "name": "create_company",
                    "arguments": {"mission_text": "A real company", "budget_cents": 5000},
                },
            )
        )["company_id"]

    # A different user's token cannot snapshot or steer it.
    async with session_factory() as db:
        r = await fm._call_tool(
            db, other, 2, {"name": "get_company_snapshot", "arguments": {"company_id": cid}}
        )
        assert "error" in r and "founder" in r["error"]["message"]


@requires_db
async def test_approve_decision_over_mcp(session_factory, monkeypatch):
    enqueued: list = []

    async def _capture(task_id):
        enqueued.append(task_id)

    monkeypatch.setattr(fm, "enqueue_task", _capture)

    async with session_factory() as db:
        u = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(u)
        await db.flush()
        company = Company(owner_user_id=u.id, name="C", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Membership(user_id=u.id, company_id=company.id, role=MembershipRole.founder))
        agent = Agent(company_id=company.id, role=AgentRole.ceo, name="CEO")
        db.add(agent)
        await db.flush()
        run = AgentRun(
            company_id=company.id, trigger=RunTrigger.scheduled, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company.id,
            run_id=run.id,
            root_run_id=run.id,
            agent_id=agent.id,
            goal="do the thing",
            status=TaskStatus.waiting_approval,
        )
        db.add(task)
        await db.flush()
        decision = DecisionRequest(
            company_id=company.id,
            agent_id=agent.id,
            task_id=task.id,
            kind=DecisionKind.plan_approval,
            summary="Approve the plan?",
            status=DecisionStatus.pending,
        )
        db.add(decision)
        await db.commit()
        uid, cid, did, tid = u.id, company.id, decision.id, task.id

    async with session_factory() as db:
        # No note: a note is archived to Company Memory, whose pgvector table is
        # excluded from the test schema — the resolution itself is what we're testing.
        r = await fm._call_tool(
            db,
            uid,
            1,
            {
                "name": "approve_decision",
                "arguments": {"company_id": str(cid), "decision_id": str(did)},
            },
        )
        assert _payload(r)["resolved"] == "approved"

    async with session_factory() as db:
        assert (await db.get(DecisionRequest, did)).status is DecisionStatus.approved
    assert tid in enqueued  # the parked task was resumed + enqueued


@requires_db
async def test_steering_tools(session_factory, monkeypatch):
    enqueued: list = []

    async def _capture(task_id):
        enqueued.append(task_id)

    monkeypatch.setattr(fm, "enqueue_task", _capture)

    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        ceo = Agent(company_id=company.id, role=AgentRole.ceo, name="CEO")
        growth = Agent(company_id=company.id, role=AgentRole.growth, name="Growth")
        db.add_all([ceo, growth])
        await db.commit()
        uid, cid, growth_id = u.id, str(company.id), growth.id

    # list_agents
    async with session_factory() as db:
        r = await fm._call_tool(
            db, uid, 1, {"name": "list_agents", "arguments": {"company_id": cid}}
        )
        roles = {a["role"] for a in _payload(r)["agents"]}
        assert {"ceo", "growth"} <= roles

    # send_founder_message to the CEO → idle agent, so a handler task is spawned + enqueued
    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            2,
            {
                "name": "send_founder_message",
                "arguments": {
                    "company_id": cid,
                    "agent_role": "ceo",
                    "message": "Focus on the launch.",
                },
            },
        )
        out = _payload(r)
        assert out["delivered_to"] == "ceo" and out["spawned"] is True
    assert len(enqueued) == 1  # the spawned handler task was enqueued

    # pause then resume the growth agent
    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            3,
            {"name": "pause_agent", "arguments": {"company_id": cid, "agent_id": str(growth_id)}},
        )
        assert _payload(r)["status"] == "paused"
    async with session_factory() as db:
        assert (await db.get(Agent, growth_id)).status is AgentStatus.paused
        r = await fm._call_tool(
            db,
            uid,
            4,
            {"name": "resume_agent", "arguments": {"company_id": cid, "agent_id": str(growth_id)}},
        )
        assert _payload(r)["status"] == "active"


@requires_db
async def test_send_message_unknown_role_errors(session_factory):
    async with session_factory() as db:
        u, company = await _active_company_with_founder(db)
        await db.commit()
        uid, cid = u.id, str(company.id)
    async with session_factory() as db:
        r = await fm._call_tool(
            db,
            uid,
            1,
            {
                "name": "send_founder_message",
                "arguments": {"company_id": cid, "agent_role": "ceo", "message": "hi"},
            },
        )
        assert "error" in r  # no active ceo agent exists → error, not a silent drop
