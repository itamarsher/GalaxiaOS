"""Enumerations shared across the data model."""

from __future__ import annotations

import enum


class CompanyStatus(str, enum.Enum):
    draft = "draft"
    launching = "launching"
    active = "active"
    paused = "paused"
    halted = "halted"


class MembershipRole(str, enum.Enum):
    founder = "founder"
    admin = "admin"


class AgentRole(str, enum.Enum):
    ceo = "ceo"
    growth = "growth"
    research = "research"
    product = "product"
    finance = "finance"
    governance = "governance"
    auditor = "auditor"
    data = "data"
    platform = "platform"
    custom = "custom"


class AutonomyLevel(str, enum.Enum):
    suggest = "suggest"
    approve_required = "approve_required"
    autonomous = "autonomous"


class AgentStatus(str, enum.Enum):
    active = "active"
    paused = "paused"


class AgentBackendType(str, enum.Enum):
    native = "native"
    external = "external"
    marketplace = "marketplace"


class AgentSource(str, enum.Enum):
    generated = "generated"
    hired = "hired"


class EdgeRelation(str, enum.Enum):
    reports_to = "reports_to"
    collaborates = "collaborates"
    escalates_to = "escalates_to"


class RunTrigger(str, enum.Enum):
    onboarding = "onboarding"
    scheduled = "scheduled"
    founder_command = "founder_command"
    agent_dispatch = "agent_dispatch"


class RunStatus(str, enum.Enum):
    running = "running"
    done = "done"
    failed = "failed"


class TaskStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    waiting_approval = "waiting_approval"
    auditing = "auditing"
    done = "done"
    failed = "failed"
    blocked = "blocked"


class SpendCategory(str, enum.Enum):
    llm = "llm"
    tool = "tool"
    external = "external"
    agent_invocation = "agent_invocation"


class BudgetPeriod(str, enum.Enum):
    monthly = "monthly"
    total = "total"


class PolicyEffect(str, enum.Enum):
    allow = "allow"
    deny = "deny"
    require_approval = "require_approval"


class PolicyScope(str, enum.Enum):
    global_ = "global"
    agent = "agent"
    category = "category"


class BreakerType(str, enum.Enum):
    spend = "spend"
    loop = "loop"
    rate = "rate"
    risky_action = "risky_action"


class BreakerState(str, enum.Enum):
    armed = "armed"
    tripped = "tripped"


class MemoryType(str, enum.Enum):
    decision = "decision"
    experiment = "experiment"
    result = "result"
    learning = "learning"
    strategy_shift = "strategy_shift"


class DecisionKind(str, enum.Enum):
    spend_approval = "spend_approval"
    risky_action = "risky_action"
    strategy = "strategy"
    plan_approval = "plan_approval"
    hire_approval = "hire_approval"
    user_action = "user_action"
    external_comm = "external_comm"  # an outbound external message awaiting sign-off


class ExternalMessageStatus(str, enum.Enum):
    """Lifecycle of an indexed outbound external communication.

    Every message an agent attempts to send outside the company is recorded with
    one of these states, so the founder can later audit (and, under the approval
    policy, gate) what the fleet says to the outside world.
    """

    pending_approval = "pending_approval"  # gated by policy; awaiting founder sign-off
    sent = "sent"  # delivered to the provider
    failed = "failed"  # attempted but the provider/tool errored
    blocked = "blocked"  # denied by policy (never attempted)
    rejected = "rejected"  # founder rejected the approval request


class DecisionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class SiteStatus(str, enum.Enum):
    """Lifecycle of a generated landing page / site."""

    draft = "draft"
    published = "published"
    failed = "failed"


class SiteConnectStatus(str, enum.Enum):
    """State machine for connecting a bought domain to a hosted site.

    Advances ``pending_ns -> ns_set -> zone_active -> attaching -> live`` as the
    DNS zone is delegated, activates, and the host accepts the custom domain.
    A reconciler job moves rows forward; ``failed`` is terminal-with-error.
    """

    pending_ns = "pending_ns"  # zone created; awaiting nameserver delegation
    ns_set = "ns_set"  # nameservers pointed at the DNS provider
    zone_active = "zone_active"  # provider reports the zone is active
    attaching = "attaching"  # custom domain submitted to the host
    live = "live"  # domain serves the site over TLS
    failed = "failed"


class ApiKeyStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"


class MetricSource(str, enum.Enum):
    """Where a real-world outcome signal came from."""

    founder = "founder"  # entered by the human founder
    agent = "agent"  # recorded by an agent via a tool
    integration = "integration"  # pulled from an external system
    simulated = "simulated"  # synthetic/dev signal


class InvestorPersona(str, enum.Enum):
    """The three onboarding investor reviewers."""

    small_business = "small_business"  # pragmatic, cash-flow / lifestyle-business lens
    startup = "startup"  # VC / venture-scale lens
    devils_advocate = "devils_advocate"  # the nay-sayer; argues the bear case


class InvestmentStance(str, enum.Enum):
    """An investor's bottom-line verdict."""

    invest = "invest"
    conditional = "conditional"
    pass_ = "pass"


class CrmContactStatus(str, enum.Enum):
    """Lifecycle stage of a CRM contact, from first touch to outcome."""

    lead = "lead"  # captured, not yet qualified
    qualified = "qualified"  # vetted as a real opportunity
    customer = "customer"  # converted / paying
    churned = "churned"  # was a customer, left
    lost = "lost"  # disqualified / dropped before converting


class CrmDealStage(str, enum.Enum):
    """Pipeline stage of a CRM deal, in pipeline order."""

    new = "new"
    qualified = "qualified"
    proposal = "proposal"
    won = "won"
    lost = "lost"


class CrmActivityKind(str, enum.Enum):
    """Type of a logged CRM interaction or planned touchpoint."""

    note = "note"
    call = "call"
    email = "email"
    meeting = "meeting"
    task = "task"
    followup = "followup"


class FileCategory(str, enum.Enum):
    """Where a stored file lives in the company's external file store (Drive).

    Each value maps to a top-level folder under ``.abos/<company>/`` (see
    :data:`app.services.files.CATEGORY_FOLDERS`). The taxonomy is chosen so the
    store can satisfy a financial audit, a due-diligence data room, and shared
    brand/knowledge — the goals the file provider exists to serve.
    """

    artifact = "artifact"  # agent-produced deliverables (copy, docs, designs, plans)
    financial = "financial"  # invoices, statements, transactions — audit trail
    data_room = "data_room"  # due-diligence-ready documents
    brand = "brand"  # shared messaging + design guidelines
    inbox = "inbox"  # noteworthy files received via external channels
    communications = "communications"  # outbound comms log (e.g. emails sent)
    knowledge = "knowledge"  # other knowledge to retain in external storage
