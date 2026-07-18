"""Data-segmentation enforcement on the file paths (RFC 0001).

Covers default classification of a filed document by category, and that the
file tools gate list/read by the calling agent's access (the CEO bypasses).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models import Budget, Company, CompanyFile, User
from app.models.enums import AgentRole, BudgetPeriod, CompanyStatus
from app.runtime.tools.files import _list_company_files, _read_company_file
from app.services import data_policy
from tests.conftest import requires_db


def test_default_labels_for_category():
    assert data_policy.default_labels_for_category("financial") == ["financial"]
    assert data_policy.default_labels_for_category("data_room") == ["legal"]
    assert data_policy.default_labels_for_category("brand") == ["marketing"]
    assert data_policy.default_labels_for_category("artifact") == []  # general


async def _company(session_factory):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Budget(company_id=company.id, period=BudgetPeriod.monthly, limit_cents=10_000))
        # A financial (labelled) file and an artifact (unlabelled/general) file.
        db.add(CompanyFile(company_id=company.id, category="financial", labels=["financial"],
                           name="Q3 statement.pdf", mime_type="application/pdf",
                           folder_path=".x", provider="google_drive"))
        db.add(CompanyFile(company_id=company.id, category="artifact", labels=[],
                           name="blog draft.md", mime_type="text/markdown",
                           folder_path=".x", provider="google_drive"))
        await db.commit()
        return company.id


def _agent(company_id, *, role, access_labels):
    return SimpleNamespace(id=uuid.uuid4(), company_id=company_id, role=role,
                           access_labels=access_labels)


@requires_db
async def test_list_tool_filters_by_access(session_factory):
    company_id = await _company(session_factory)
    async with session_factory() as db:
        ctx = SimpleNamespace(session_factory=session_factory)
        task = SimpleNamespace(company_id=company_id)

        # A growth agent without the "financial" label sees only the general file.
        growth = _agent(company_id, role=AgentRole.growth, access_labels=[])
        out = await _list_company_files(db, ctx, agent=growth, task=task, args={})
        assert "blog draft.md" in out.observation and "Q3 statement.pdf" not in out.observation

        # Grant it "financial" → it now sees the statement too.
        growth.access_labels = ["financial"]
        out = await _list_company_files(db, ctx, agent=growth, task=task, args={})
        assert "Q3 statement.pdf" in out.observation

        # The CEO bypasses segmentation entirely.
        ceo = _agent(company_id, role=AgentRole.ceo, access_labels=None)
        out = await _list_company_files(db, ctx, agent=ceo, task=task, args={})
        assert "Q3 statement.pdf" in out.observation and "blog draft.md" in out.observation


@requires_db
async def test_read_tool_denies_without_clearance(session_factory):
    company_id = await _company(session_factory)
    async with session_factory() as db:
        ctx = SimpleNamespace(session_factory=session_factory)
        task = SimpleNamespace(company_id=company_id)

        growth = _agent(company_id, role=AgentRole.growth, access_labels=[])
        # Denied read looks identical to "no such file" so labels aren't probeable.
        out = await _read_company_file(db, ctx, agent=growth, task=task,
                                       args={"name": "Q3 statement.pdf"})
        assert out.is_error and "No filed document" in out.observation
