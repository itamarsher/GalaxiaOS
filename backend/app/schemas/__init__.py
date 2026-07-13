"""Pydantic v2 request/response DTOs (the source of truth for the OpenAPI schema)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ORMModel(BaseModel):
    model_config = {"from_attributes": True}


# ── Auth ─────────────────────────────────────────────────────────────────────
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    name: str | None = None


class GoogleAuthStatusOut(BaseModel):
    """Whether "Sign in with Google" is available on this deployment."""

    enabled: bool


class AuthorizeUrlOut(BaseModel):
    """A Google consent URL the browser is redirected to, to begin an OAuth flow."""

    authorize_url: str


# ── Onboarding ───────────────────────────────────────────────────────────────
class OnboardingStartRequest(BaseModel):
    mission_text: str = Field(min_length=4)
    budget_cents: int = Field(gt=0, description="Monthly budget in cents, e.g. 50000 = $500")
    constraints: list[str] = Field(default_factory=list)


class CompanyOut(ORMModel):
    id: uuid.UUID
    name: str
    status: str
    mission_id: uuid.UUID | None = None
    email_from: str | None = None


class CompanyUpdateRequest(BaseModel):
    """Founder-editable company settings. Fields left unset are not changed."""

    # Sender ("From:") address agents send mail as, e.g. ``Acme <hello@acme.com>``
    # or ``hello@acme.com``. Empty string clears it (falls back to the global
    # default). Validated loosely — it must contain an ``@`` — so display names
    # and angle-bracket forms are accepted.
    email_from: str | None = Field(default=None, max_length=320)


class PlaybookOut(BaseModel):
    """The company's global operating playbook (the system prompt every agent gets)."""

    playbook: str  # the effective text (custom if set, else the platform default)
    customized: bool  # True once the founder/CEO has overridden the default
    default: str  # the platform default, so the UI can offer "reset"


class PlaybookUpdateRequest(BaseModel):
    # The full new playbook. Empty string clears the override (reverts to default).
    playbook: str = Field(max_length=8000)


class KeyResultOut(ORMModel):
    id: uuid.UUID
    metric: str
    target_value: float | None
    current_value: float
    unit: str | None


class ObjectiveOut(ORMModel):
    id: uuid.UUID
    title: str
    rationale: str | None
    priority: int
    status: str


class AgentOut(ORMModel):
    id: uuid.UUID
    role: str
    name: str
    autonomy_level: str
    status: str
    monthly_budget_cents: int | None
    reports_to_agent_id: uuid.UUID | None
    backend_type: str
    source: str
    # The agent's launch prompt, surfaced so the founder can see how each agent is
    # directed: ``system_prompt`` is the agent's company-specific directive (editable
    # by the CEO); ``role_description`` is the fixed behaviour for its role.
    system_prompt: str = ""
    role_description: str = ""


class AgentEdgeOut(ORMModel):
    from_agent_id: uuid.UUID
    to_agent_id: uuid.UUID
    relation: str


class OrgChartOut(BaseModel):
    agents: list[AgentOut]
    edges: list[AgentEdgeOut]


class InvestmentReviewOut(ORMModel):
    id: uuid.UUID
    persona: str
    stance: str
    conviction: int
    headline: str
    thesis: str
    strengths: list | None = None
    risks: list | None = None
    conditions: list | None = None


class PreviewOut(BaseModel):
    company: CompanyOut
    objectives: list[ObjectiveOut]
    org: OrgChartOut
    cost_estimate_cents: int | None = None
    investment_reviews: list[InvestmentReviewOut] = Field(default_factory=list)


# ── Sites & connected domains ────────────────────────────────────────────────
class SiteDomainOut(ORMModel):
    id: uuid.UUID
    domain: str
    status: str


class SiteOut(ORMModel):
    id: uuid.UUID
    slug: str
    title: str
    status: str
    deployment_url: str | None = None
    created_at: datetime
    domains: list[SiteDomainOut] = []
    cost_estimate_cents: int | None = None
    investment_reviews: list[InvestmentReviewOut] = Field(default_factory=list)
    # Early-signal leads captured by this page's built-in form.
    lead_count: int = 0


class SiteLeadOut(ORMModel):
    id: uuid.UUID
    site_id: uuid.UUID | None = None
    email: str
    name: str | None = None
    message: str | None = None
    source: str | None = None
    created_at: datetime


# ── Domains space ────────────────────────────────────────────────────────────
class DomainQuoteOut(BaseModel):
    domain: str
    available: bool
    price_cents: int


class DomainOut(ORMModel):
    id: uuid.UUID
    domain: str
    status: str
    site_id: uuid.UUID | None = None
    last_error: str | None = None
    created_at: datetime


class DomainCapabilitiesOut(BaseModel):
    registrar: str
    can_buy: bool
    can_connect: bool
    can_send_email: bool


class DomainPurchaseRequest(BaseModel):
    domain: str
    site_id: uuid.UUID | None = None


class DomainAssociateRequest(BaseModel):
    site_id: uuid.UUID


class EmailSetupRequest(BaseModel):
    domain: str


class EmailDnsRecordOut(BaseModel):
    record: str
    type: str
    name: str
    ok: bool
    error: str | None = None


class EmailSetupOut(BaseModel):
    domain: str
    status: str
    all_written: bool
    records: list[EmailDnsRecordOut]


class EmailStatusOut(BaseModel):
    domain: str
    configured: bool
    status: str
    pending: list[str]


class GenerationEvent(BaseModel):
    ts: float
    label: str
    pct: int


class GenerationProgressOut(BaseModel):
    phase: str
    pct: int
    message: str
    status: str  # "idle" | "running" | "done" | "error"
    error: str | None = None
    events: list[GenerationEvent] = Field(default_factory=list)


class RefineRequest(BaseModel):
    message: str = Field(min_length=1)


class RefineResponse(BaseModel):
    reply: str
    preview: PreviewOut


# ── Reuse saved keys & connections from another business ─────────────────────
class ReusableCredentialOut(BaseModel):
    """A key/connection from one of the founder's other companies, offered for
    one-click reuse during a new company's onboarding. Never carries a secret."""

    id: str  # opaque selection id, e.g. "key:anthropic" or "mcp:acme_crm"
    kind: str  # "key" | "connection"
    provider: str | None = None
    label: str
    detail: str | None = None  # display fingerprint / tool count — never a secret
    source_company_id: uuid.UUID
    source_company_name: str


class ReuseCredentialsRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class ReuseCredentialsResponse(BaseModel):
    reused: list[str] = Field(default_factory=list)


# ── API keys ─────────────────────────────────────────────────────────────────
class ApiKeyCreateRequest(BaseModel):
    provider: str = "anthropic"
    api_key: str = Field(min_length=8)


class ApiKeyOut(ORMModel):
    id: uuid.UUID
    provider: str
    key_fingerprint: str
    status: str


# ── Integrations (Cloudflare site host + DNS) ────────────────────────────────
class CloudflareCredsRequest(BaseModel):
    api_token: str = Field(min_length=8)
    account_id: str = Field(min_length=8)


class CloudflareStatusOut(BaseModel):
    configured: bool
    account_id: str | None = None


# ── Integrations (Google Drive file store) ───────────────────────────────────
class GoogleDriveStatusOut(BaseModel):
    configured: bool
    root_folder_id: str | None = None
    # Whether one-click "Connect with Google" is available (i.e. the deployment
    # has a Google OAuth app configured). When false, Drive can't be connected.
    connect_available: bool = False


class GoogleDriveConnectOut(BaseModel):
    """The Google consent URL the browser is redirected to, to start connect."""

    authorize_url: str


class CompanyFileOut(ORMModel):
    id: uuid.UUID
    category: str
    name: str
    description: str | None = None
    mime_type: str
    folder_path: str
    web_url: str | None = None
    size_bytes: int | None = None
    created_at: datetime


# ── MCP servers (founder-pluggable tools) ────────────────────────────────────
class McpServerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="Short slug, e.g. 'acme-crm'.")
    label: str | None = Field(default=None, max_length=255)
    url: str = Field(min_length=4, max_length=1024)
    transport: str = "http"
    auth_token: str | None = Field(
        default=None, description="Optional bearer token; encrypted at rest."
    )


class McpServerOut(BaseModel):
    id: uuid.UUID
    name: str
    label: str
    url: str
    transport: str
    enabled: bool
    has_auth: bool
    tool_count: int
    tools: list[str] = Field(default_factory=list)
    last_error: str | None = None


# ── Artifacts (founder-facing reports) ────────────────────────────────────────
class ArtifactListOut(ORMModel):
    id: uuid.UUID
    kind: str
    title: str
    source_task_id: uuid.UUID | None = None
    source_agent_id: uuid.UUID | None = None
    created_at: datetime


class ArtifactOut(ArtifactListOut):
    body_md: str


class ArtifactGenerateRequest(BaseModel):
    kind: str = "custom"
    instructions: str | None = None


# ── Budget ───────────────────────────────────────────────────────────────────
class BudgetOut(ORMModel):
    id: uuid.UUID
    limit_cents: int
    spent_cents: int
    reserved_cents: int
    currency: str


class BudgetView(BaseModel):
    budget: BudgetOut
    by_category: dict[str, int]
    by_agent: dict[str, int]


class BudgetPatchRequest(BaseModel):
    limit_cents: int = Field(gt=0)


# ── Tasks / runs ─────────────────────────────────────────────────────────────
class TaskOut(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    parent_task_id: uuid.UUID | None
    objective_id: uuid.UUID | None = None
    root_run_id: uuid.UUID | None
    depth: int
    goal: str
    status: str
    cost_cents: int
    output: dict | None
    created_at: datetime


class CycleStartOut(BaseModel):
    """Result of POST /companies/{id}/cycle."""

    started: bool
    task_id: uuid.UUID | None = None
    # started | already_running | not_active | insufficient_budget | spend_breaker | no_ceo
    reason: str
    active: bool  # a cycle is in progress after this call (started OR already_running)


class CycleStatusOut(BaseModel):
    """Result of GET /companies/{id}/cycle — drives the Advance button state."""

    active: bool
    can_start: bool
    reason: str  # "ready" when can_start, else the block reason
    active_task_count: int


class TaskDetailOut(TaskOut):
    agent_name: str | None = None
    agent_role: str | None = None
    input: dict | None = None
    children: list[TaskOut] = Field(default_factory=list)
    pending_decision: "DecisionOut | None" = None


class TaskTranscriptOut(BaseModel):
    """A live tail of a running task's working memory (last N rendered lines)."""

    task_id: uuid.UUID
    status: str
    lines: list[str] = Field(default_factory=list)


# ── Budget detail ────────────────────────────────────────────────────────────
class SpendEntryOut(ORMModel):
    id: uuid.UUID
    category: str
    amount_cents: int
    vendor: str | None = None
    sku: str | None = None
    description: str | None = None
    task_id: uuid.UUID | None = None
    created_at: datetime


class AgentSpendOut(BaseModel):
    agent_id: uuid.UUID | None
    agent_name: str | None = None
    agent_role: str | None = None
    total_cents: int
    entries: list[SpendEntryOut] = Field(default_factory=list)


# ── Governance ───────────────────────────────────────────────────────────────
class PolicyOut(ORMModel):
    id: uuid.UUID
    name: str
    enabled: bool
    scope: str
    rule: dict
    effect: str
    priority: int


class PolicyCreateRequest(BaseModel):
    name: str
    scope: str = "global"
    rule: dict
    effect: str
    priority: int = 100
    enabled: bool = True


class BreakerOut(ORMModel):
    id: uuid.UUID
    type: str
    state: str
    tripped_reason: str | None


class ReputationOut(ORMModel):
    agent_id: uuid.UUID
    agent_name: str | None = None
    agent_role: str | None = None
    trust: float
    accuracy: float
    roi: float
    reliability: float
    sample_count: int


class DecisionOut(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None = None
    agent_role: str | None = None
    task_id: uuid.UUID | None
    kind: str
    summary: str
    status: str
    created_at: datetime
    # Bigger-picture context, attached at read time (see decisions API _to_out).
    task_goal: str | None = None  # the ask that triggered this decision
    initiative: str | None = None  # the higher-level initiative it belongs to
    objective_title: str | None = None  # best-effort related objective


class DecisionResolveRequest(BaseModel):
    note: str | None = None


# ── External communications ──────────────────────────────────────────────────
class ExternalMessageOut(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None = None  # joined at read time
    agent_role: str | None = None
    task_id: uuid.UUID | None
    decision_id: uuid.UUID | None
    tool: str
    channel: str
    recipient: str | None
    subject: str | None
    body: str | None
    status: str
    detail: str | None
    created_at: datetime


class ExternalApprovalSetting(BaseModel):
    """Whether outbound communication is gated behind founder approval."""

    enabled: bool


class ExternalApprovalUpdate(BaseModel):
    enabled: bool


# ── Chat (fleet + founder collaboration) ─────────────────────────────────────
class ChatParticipantOut(BaseModel):
    agent_id: uuid.UUID | None = None  # None = the founder
    name: str  # "Founder", or the agent's name
    role: str | None = None  # the agent's role, when not the founder


class ChatMessageOut(ORMModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    thread_id: uuid.UUID | None = None  # None = the channel's main timeline
    sender_agent_id: uuid.UUID | None = None  # None = the founder
    sender_name: str | None = None  # joined at read time
    sender_role: str | None = None
    is_founder: bool = False
    body: str
    created_at: datetime


class ChatThreadOut(ORMModel):
    """A named sub-conversation inside a channel (a parallel sub-initiative)."""

    id: uuid.UUID
    channel_id: uuid.UUID
    title: str
    archived: bool = False
    created_at: datetime
    message_count: int = 0
    last_message_at: datetime | None = None
    # Per-thread loop guard, mirroring the channel's.
    message_budget: int = 10
    escalation_pending: bool = False


class ChatChannelOut(ORMModel):
    id: uuid.UUID
    name: str
    purpose: str | None = None
    kind: str
    archived: bool = False
    created_at: datetime
    participants: list[ChatParticipantOut] = Field(default_factory=list)
    message_count: int = 0
    # Open threads (sub-conversations) in this channel, newest first.
    threads: list[ChatThreadOut] = Field(default_factory=list)
    # Loop guard: messages allowed before the next CEO review, and whether posting
    # is currently paused because that review is open (see app.runtime.tools.chat).
    message_budget: int = 10
    escalation_pending: bool = False
    last_message_at: datetime | None = None
    last_message_preview: str | None = None
    # Names of agents currently parked waiting for a reply in this channel — the
    # "an agent needs you" signal the founder acts on (like the decision inbox).
    waiting_agents: list[str] = Field(default_factory=list)
    # A structured decision awaiting the founder in this thread (budget/plan/hire/
    # external). When set, the UI offers Approve/Reject inline; open-ended asks
    # have no decision here and are resolved by simply replying.
    pending_decision: DecisionOut | None = None


class ChatChannelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    purpose: str | None = Field(default=None, max_length=2000)
    # Agent roles to add as members (the founder is always a member).
    member_roles: list[str] = Field(default_factory=list)


class ChatPostRequest(BaseModel):
    message: str = Field(min_length=1)
    # Reply into a specific thread (sub-conversation); omit for the main timeline.
    thread_id: uuid.UUID | None = None


# ── Memory / Copilot ─────────────────────────────────────────────────────────
class MemoryOut(ORMModel):
    id: uuid.UUID
    type: str
    title: str
    content: str
    created_at: datetime


class CopilotAskRequest(BaseModel):
    question: str


class CopilotAskResponse(BaseModel):
    answer: str
    kind: str  # "query" | "command"


# ── Marketplace ──────────────────────────────────────────────────────────────
class AgentListingOut(ORMModel):
    id: uuid.UUID
    name: str
    role: str
    description: str
    provider: str
    price_cents: int
    trust: float | None = None
    accuracy: float | None = None
    roi: float | None = None
    reliability: float | None = None


class HireAgentRequest(BaseModel):
    listing_id: uuid.UUID


# ── Feature requests (capabilities the platform delivers) ────────────────────
class FeatureRequesterOut(BaseModel):
    """Who, inside this company, asked for a capability — an agent or the founder."""

    agent_id: uuid.UUID | None = None
    agent_name: str | None = None
    user_email: str | None = None
    details: str | None = None


class FeatureRequestOut(BaseModel):
    """A capability/bug this company requested, with its delivery status.

    The founder-facing view of the platform backlog: what the company's agents (and
    founders) asked the platform for, and whether it has been delivered.
    """

    id: uuid.UUID
    kind: str
    title: str
    details: str
    status: str  # open | promoted | delivered
    vote_count: int
    github_issue_number: int | None = None
    github_issue_url: str | None = None
    created_at: datetime
    requesters: list[FeatureRequesterOut]


# Resolve the forward reference from TaskDetailOut -> DecisionOut.
TaskDetailOut.model_rebuild()
