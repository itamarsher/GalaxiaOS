"""Company views: detail, org chart, agents (pause/resume), runs/tasks, memory."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import (
    Agent,
    AgentEdge,
    Company,
    DecisionRequest,
    Membership,
    MemoryEntry,
    SiteDomain,
    Task,
)
from app.models.enums import AgentStatus, DecisionStatus, TaskStatus
from app.runtime.transcript import transcript_lines
from app.schemas import (
    AgentEdgeOut,
    AgentOut,
    CompanyOut,
    DecisionOut,
    MemoryOut,
    OrgChartOut,
    SiteDomainOut,
    SiteOut,
    TaskDetailOut,
    TaskOut,
    TaskTranscriptOut,
)
from app.services import sites as sites_svc

router = APIRouter(prefix="/companies/{company_id}", tags=["companies"])

# A second router (no company_id prefix) for account-level listing: a user can
# own/run multiple businesses, so they need to enumerate them.
mine_router = APIRouter(tags=["companies"])


@mine_router.get("/companies", response_model=list[CompanyOut])
async def list_my_companies(db: DbDep, user: CurrentUser):
    """Every company the current user is a member of, newest first."""
    rows = await db.scalars(
        select(Company)
        .join(Membership, Membership.company_id == Company.id)
        .where(Membership.user_id == user.id)
        .order_by(Company.created_at.desc())
    )
    return list(rows)


@router.get("", response_model=CompanyOut)
async def get_company(company: CompanyDep):
    return company


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company: CompanyDep, db: DbDep):
    """Permanently delete a company and everything under it.

    This is the founder's hard stop: removing the company row cascades (via the
    ``company_id`` ON DELETE CASCADE on every tenant table) to its agents, runs,
    tasks, budget, governance, memory and digests, so no further scheduled or
    in-flight work can run for it.
    """
    await db.delete(company)
    await db.commit()
    return None


@router.get("/org", response_model=OrgChartOut)
async def org_chart(company: CompanyDep, db: DbDep):
    agents = (await db.scalars(select(Agent).where(Agent.company_id == company.id))).all()
    edges = (await db.scalars(select(AgentEdge).where(AgentEdge.company_id == company.id))).all()
    return OrgChartOut(
        agents=[AgentOut.model_validate(a) for a in agents],
        edges=[AgentEdgeOut.model_validate(e) for e in edges],
    )


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(company: CompanyDep, db: DbDep):
    return (await db.scalars(select(Agent).where(Agent.company_id == company.id))).all()


@router.post("/agents/{agent_id}/pause", response_model=AgentOut)
async def pause_agent(company: CompanyDep, agent_id: uuid.UUID, db: DbDep):
    return await _set_agent_status(db, company.id, agent_id, AgentStatus.paused)


@router.post("/agents/{agent_id}/resume", response_model=AgentOut)
async def resume_agent(company: CompanyDep, agent_id: uuid.UUID, db: DbDep):
    return await _set_agent_status(db, company.id, agent_id, AgentStatus.active)


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(company: CompanyDep, db: DbDep):
    """Generated landing pages and the bought domains connected to each."""
    sites = await sites_svc.list_sites(db, company_id=company.id)
    domains = (
        await db.scalars(select(SiteDomain).where(SiteDomain.company_id == company.id))
    ).all()
    by_site: dict[uuid.UUID, list[SiteDomainOut]] = {}
    for d in domains:
        if d.site_id is not None:
            by_site.setdefault(d.site_id, []).append(SiteDomainOut.model_validate(d))
    return [
        SiteOut(
            id=s.id,
            slug=s.slug,
            title=s.title,
            status=s.status.value,
            deployment_url=s.deployment_url,
            created_at=s.created_at,
            domains=by_site.get(s.id, []),
        )
        for s in sites
    ]


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(company: CompanyDep, db: DbDep, status: TaskStatus | None = None):
    stmt = select(Task).where(Task.company_id == company.id).order_by(Task.created_at.desc())
    if status is not None:
        stmt = stmt.where(Task.status == status)
    return (await db.scalars(stmt.limit(200))).all()


@router.get("/tasks/{task_id}", response_model=TaskDetailOut)
async def get_task(company: CompanyDep, task_id: uuid.UUID, db: DbDep):
    """A single task with its executing agent and any dispatched sub-tasks."""
    task = await db.scalar(
        select(Task).where(Task.company_id == company.id, Task.id == task_id)
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    agent = await db.get(Agent, task.agent_id)
    children = (
        await db.scalars(
            select(Task)
            .where(Task.parent_task_id == task.id)
            .order_by(Task.created_at.asc())
        )
    ).all()
    detail = TaskDetailOut.model_validate(task)
    detail.agent_name = agent.name if agent else None
    detail.agent_role = agent.role.value if agent else None
    detail.children = [TaskOut.model_validate(c) for c in children]
    # Surface the pending decision (if any) so the UI can show the task is
    # blocked on the founder and offer approve/reject inline.
    pending = await db.scalar(
        select(DecisionRequest)
        .where(
            DecisionRequest.task_id == task.id,
            DecisionRequest.status == DecisionStatus.pending,
        )
        .order_by(DecisionRequest.created_at.desc())
    )
    if pending is not None:
        decision_out = DecisionOut.model_validate(pending)
        decision_out.agent_name = agent.name if agent else None
        detail.pending_decision = decision_out
    return detail


@router.get("/tasks/{task_id}/transcript", response_model=TaskTranscriptOut)
async def get_task_transcript(company: CompanyDep, task_id: uuid.UUID, db: DbDep):
    """Live tail of a running task's working memory — the last 50 rendered lines.

    The transcript is the agent's in-flight conversation, checkpointed each step
    and cleared when the task finishes (see :mod:`app.runtime.backends.native`).
    So this streams the agent's progress while it works and returns an empty list
    once the task is done — the result then lives on the task detail itself.
    """
    task = await db.scalar(
        select(Task).where(Task.company_id == company.id, Task.id == task_id)
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return TaskTranscriptOut(
        task_id=task.id,
        status=task.status.value,
        lines=transcript_lines(task.transcript, limit=50),
    )


@router.get("/memory", response_model=list[MemoryOut])
async def list_memory(company: CompanyDep, db: DbDep, q: str | None = None):
    stmt = (
        select(MemoryEntry)
        .where(MemoryEntry.company_id == company.id)
        .order_by(MemoryEntry.created_at.desc())
    )
    if q:
        stmt = stmt.where(MemoryEntry.content.ilike(f"%{q}%"))
    return (await db.scalars(stmt.limit(100))).all()


async def _set_agent_status(db, company_id, agent_id, new_status):
    agent = await db.scalar(
        select(Agent).where(Agent.company_id == company_id, Agent.id == agent_id)
    )
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    agent.status = new_status
    await db.commit()
    return agent
