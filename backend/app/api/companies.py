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
    Mission,
    Objective,
    SiteDomain,
    Task,
)
from app.models.enums import AgentStatus, DecisionStatus, TaskStatus
from app.runtime.prompts import ROLE_DESCRIPTIONS, effective_playbook
from app.runtime.transcript import transcript_lines
from app.schemas import (
    AgentEdgeOut,
    AgentOut,
    CompanyOut,
    CompanyUpdateRequest,
    CycleStartOut,
    CycleStatusOut,
    DecisionOut,
    FeatureRequesterOut,
    FeatureRequestOut,
    MemoryOut,
    MissionOut,
    ObjectiveOut,
    OrgChartOut,
    PlaybookOut,
    PlaybookUpdateRequest,
    ResetCompanyRequest,
    SiteDomainOut,
    SiteLeadOut,
    SiteOut,
    TaskDetailOut,
    TaskOut,
    TaskTranscriptOut,
)
from app.services import company_reset as company_reset_svc
from app.services import feature_requests as fr_svc
from app.services import memory as memory_svc
from app.services import runs as runs_svc
from app.services import sites as sites_svc


def _agent_out(agent: Agent) -> AgentOut:
    """Serialize an agent, attaching the fixed role description for its role.

    ``system_prompt`` (the agent's editable directive) comes straight off the ORM
    row; ``role_description`` is computed from the role so the founder sees the
    agent's full launch prompt — both the standing role behaviour and the
    company-specific directive.
    """
    out = AgentOut.model_validate(agent)
    out.role_description = ROLE_DESCRIPTIONS.get(agent.role, "")
    return out


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


@router.patch("", response_model=CompanyOut)
async def update_company(company: CompanyDep, body: CompanyUpdateRequest, db: DbDep):
    """Update founder-editable company settings (currently the sender address).

    ``email_from`` is the "From:" agents send mail as; with Resend it must be on a
    domain verified in the founder's Resend account. An empty string clears it
    (falls back to the global ``ABOS_EMAIL_FROM``).
    """
    if body.email_from is not None:
        sender = body.email_from.strip()
        if sender and "@" not in sender:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Sender must be an email address, e.g. hello@acme.com or 'Acme <hello@acme.com>'.",
            )
        company.email_from = sender or None
    await db.commit()
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


@router.get("/mission", response_model=MissionOut)
async def get_mission(company: CompanyDep, db: DbDep):
    """The company's current mission text + constraints.

    Lets the UI prefill the mission editor (e.g. before a reset/relaunch) with what
    the company is running today.
    """
    mission = await db.scalar(select(Mission).where(Mission.company_id == company.id))
    if mission is None:
        return MissionOut(mission_text="", constraints=[])
    return MissionOut(mission_text=mission.raw_text, constraints=list(mission.constraints or []))


@router.post("/reset", response_model=CompanyOut)
async def reset_company(company: CompanyDep, db: DbDep, body: ResetCompanyRequest | None = None):
    """Reset this company to a fresh draft, preserving its saved keys.

    Wipes the generated org and all operational state (tasks, runs, budget spend,
    memory, chat, sites, decisions, …) and re-provisions the default fleet,
    returning the company to the onboarding plan-approval (``draft``) state so the
    founder can refine, regenerate, or relaunch. Saved BYOK provider keys survive.

    The mission is preserved by default, but the founder can **edit it as part of
    the relaunch**: an optional body may carry a revised ``mission_text`` and/or
    ``constraints``. Omitting the body (or a field) keeps the current value.
    """
    body = body or ResetCompanyRequest()
    fresh = await company_reset_svc.reset_company(
        db, company=company, mission_text=body.mission_text, constraints=body.constraints
    )
    await db.commit()
    return fresh


@router.post("/cycle", response_model=CycleStartOut)
async def advance_cycle(company: CompanyDep, db: DbDep):
    """Start one business cycle for this company on demand — the game's "round".

    Mirrors the ``run_business_cycle`` cron for a single company: guards on active
    status, an already-running cycle (continuous mode may be looping), and the
    budget/spend-breaker gate, then kicks a CEO scheduled run. Commits before
    enqueuing (the cron's ordering) so the queued task always sees the committed
    row. Returns why it did/didn't start so the UI can label the button.
    """
    from app.runtime.queue import enqueue_task

    result = await runs_svc.start_cycle(db, company)
    if result.started and result.task_id is not None:
        await db.commit()
        await enqueue_task(result.task_id)
    return CycleStartOut(
        started=result.started,
        task_id=result.task_id,
        reason=result.reason,
        active=result.active,
    )


@router.get("/cycle", response_model=CycleStatusOut)
async def cycle_status(company: CompanyDep, db: DbDep):
    """Whether a cycle is in progress and whether a new one can start now."""
    status_ = await runs_svc.cycle_status(db, company)
    return CycleStatusOut(
        active=status_.active,
        can_start=status_.can_start,
        reason=status_.reason,
        active_task_count=status_.active_task_count,
    )


@router.get("/playbook", response_model=PlaybookOut)
async def get_playbook(company: CompanyDep):
    """The company's global operating playbook — the system prompt every agent runs
    under. Returns the effective text (custom if set, else the platform default),
    whether it's been customized, and the default (so the UI can offer a reset)."""
    raw = (company.playbook or "").strip()
    return PlaybookOut(
        playbook=effective_playbook(company.playbook),
        customized=bool(raw),
        default=effective_playbook(None),
    )


@router.put("/playbook", response_model=PlaybookOut)
async def update_playbook(company: CompanyDep, body: PlaybookUpdateRequest, db: DbDep):
    """Founder edit of the global playbook. An empty string clears the override and
    reverts every agent to the platform default."""
    text = body.playbook.strip()
    company.playbook = text or None
    await db.commit()
    return PlaybookOut(
        playbook=effective_playbook(company.playbook),
        customized=bool(text),
        default=effective_playbook(None),
    )


@router.get("/org", response_model=OrgChartOut)
async def org_chart(company: CompanyDep, db: DbDep):
    agents = (await db.scalars(select(Agent).where(Agent.company_id == company.id))).all()
    edges = (await db.scalars(select(AgentEdge).where(AgentEdge.company_id == company.id))).all()
    return OrgChartOut(
        agents=[_agent_out(a) for a in agents],
        edges=[AgentEdgeOut.model_validate(e) for e in edges],
    )


@router.get("/objectives", response_model=list[ObjectiveOut])
async def list_objectives(company: CompanyDep, db: DbDep):
    """The company's mission objectives — the source for the game's active quests.

    Ordered by priority (highest-priority objective first) so the quest log leads
    with what matters most. Both active and completed objectives are returned; the
    client keeps active ones on the board and files completed ones under a
    "cleared" section.
    """
    objectives = (
        await db.scalars(
            select(Objective)
            .where(Objective.company_id == company.id)
            .order_by(Objective.priority)
        )
    ).all()
    return [ObjectiveOut.model_validate(o) for o in objectives]


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(company: CompanyDep, db: DbDep):
    agents = (await db.scalars(select(Agent).where(Agent.company_id == company.id))).all()
    return [_agent_out(a) for a in agents]


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
    counts = await sites_svc.lead_counts(db, company_id=company.id)
    return [
        SiteOut(
            id=s.id,
            slug=s.slug,
            title=s.title,
            status=s.status.value,
            deployment_url=s.deployment_url,
            created_at=s.created_at,
            domains=by_site.get(s.id, []),
            lead_count=counts.get(s.id, 0),
        )
        for s in sites
    ]


@router.get("/sites/leads", response_model=list[SiteLeadOut])
async def list_all_leads(company: CompanyDep, db: DbDep):
    """Every early-signal lead captured across the company's landing pages."""
    leads = await sites_svc.list_leads(db, company_id=company.id)
    return [SiteLeadOut.model_validate(lead) for lead in leads]


@router.get("/sites/{site_id}/leads", response_model=list[SiteLeadOut])
async def list_site_leads(company: CompanyDep, db: DbDep, site_id: uuid.UUID):
    """Early-signal leads captured by one landing page."""
    leads = await sites_svc.list_leads(db, company_id=company.id, site_id=site_id)
    return [SiteLeadOut.model_validate(lead) for lead in leads]


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
    """The company's memory. With a query, ranks by similarity + recency — the same
    recall the agents use — instead of a keyword match; without one, most recent."""
    return await memory_svc.query(db, company_id=company.id, text=q, limit=100)


@router.delete("/memory/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(company: CompanyDep, entry_id: uuid.UUID, db: DbDep):
    """Forget a memory entry (founder curation of the company brain)."""
    removed = await memory_svc.delete(db, company_id=company.id, entry_id=entry_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memory entry not found")
    await db.commit()


@router.get("/feature-requests", response_model=list[FeatureRequestOut])
async def list_feature_requests(company: CompanyDep, db: DbDep):
    """Capabilities/bugs this company asked the platform for, and their delivery status.

    The founder's audit of the request→delivery loop: every backlog entry the
    company's agents (or founders) requested, which agent asked, and whether the
    platform has promoted it into a tracker issue and delivered it. Newest first.
    """
    requests = await fr_svc.list_for_company(db, company_id=company.id)
    return [
        FeatureRequestOut(
            id=cr.feature_request.id,
            kind=cr.feature_request.kind.value,
            title=cr.feature_request.title,
            details=cr.feature_request.details,
            status=cr.feature_request.status.value,
            vote_count=cr.feature_request.vote_count,
            github_issue_number=cr.feature_request.github_issue_number,
            github_issue_url=cr.feature_request.github_issue_url,
            created_at=cr.feature_request.created_at,
            requesters=[
                FeatureRequesterOut(
                    agent_id=a.agent_id,
                    agent_name=a.agent_name,
                    user_email=a.user_email,
                    details=a.details,
                )
                for a in cr.attributions
            ],
        )
        for cr in requests
    ]


async def _set_agent_status(db, company_id, agent_id, new_status):
    agent = await db.scalar(
        select(Agent).where(Agent.company_id == company_id, Agent.id == agent_id)
    )
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    agent.status = new_status
    await db.commit()
    return agent
