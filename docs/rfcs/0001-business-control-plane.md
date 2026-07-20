# RFC 0001 — Galaxia as the business control plane; a hybrid workforce connects in

- **Status:** Draft v2 (for discussion)
- **Scope:** Architecture direction. No code changes in this PR.
- **Supersedes:** nothing yet. Establishes the target for the runtime layer.
- **v2 change:** generalized from "external agents connect in" to a **hybrid
  workforce** — a *function slot* filled by an internal agent, an external agent,
  **or a human**, interchangeably. See [§1a](#1a-worker-bindings--the-hybrid-workforce).

## Summary

Today Galaxia does two very different jobs, and only one of them is
differentiated:

- **Job A — the business brain (differentiated).** Turn a *mission + budget* into
  a *designed org*: objectives/KRs, the right functions, budget discipline,
  governance/approvals, cross-function coordination, institutional memory, and the
  founder-as-board-member control loop.
- **Job B — the agent runtime (undifferentiated treadmill).** A think→act loop,
  tool calling, tool discovery, an MCP client, vector memory, context compaction.
  Claude Code, OpenClaw, Codex and others already do this well and improve weekly.

This RFC proposes we **stop owning Job B** and reframe Galaxia as a **business
control plane that a hybrid workforce connects *into***. A **function** (Growth,
Product, QA…) is a *slot* in the generated org; each slot is filled by a
**worker** — an internal agent, an external agent, or a human — through one
identical interface. The worker fetches its **mandate** (which function it is, the
mission, its objectives, budget envelope, current state) and its **next
initiative**, does the work with *its own* capabilities, and **reports results
back**. Galaxia keeps what's hard and unique — the org design, governance, budget,
coordination, and institutional memory — and delegates *execution* to whoever (or
whatever) staffs the function.

We evaluated **OpenClaw** (`openclaw/openclaw`, MIT) as the reference external
runtime and found it a strong fit (see [§7](#7-reference-runtime-openclaw)).

## Motivation

1. **We are reinventing plumbing we can't win at.** `runtime/backends/native.py`
   is a full agent harness — perceive → think → act, tool discovery
   (`discover_tools`/`use_tool`), an MCP client, budget-aware retries, transcript
   compaction. Every week that Claude Code / OpenClaw / Codex improve, our
   in-house loop falls further behind at a job that isn't our product.
2. **Our recent dogfooding pain was Job B, not Job A.** The competence fixes
   (#170/#171), the publish-HTML bug (#172), the media-quota surfacing (#173), and
   the `dispatch_task` "product agent acting as designer" routing gap were all
   runtime-plumbing problems. The *business* layer (objectives, governance,
   budget) behaved.
3. **The mission already commits to this seam.** `MISSION.md` names `AgentBackend`
   ("how an agent executes") and `LLMProvider` as decoupling seams so "the free
   core never traps you in a single vendor or a single way of running agents."
   This RFC leans into a seam we already declared, rather than inventing one.
4. **It unlocks "import an existing business."** If functions are external agents
   (or people) that bind to Galaxia's function slots, then onboarding an
   *existing* operation is the same protocol as launching a new one — you don't
   rebuild their tooling, you give them the objectives/governance/coordination
   layer on top.

## Goals

- Galaxia owns the **business**: org design, objectives/KRs, initiatives, budget
  envelopes, governance/approvals, coordination, institutional memory,
  multi-tenant isolation.
- Any MCP-capable agent runtime can be a business function by connecting to a
  Galaxia **Business-Function MCP server** with a per-`(company, function)`
  identity.
- Preserve the **"mission + budget → running business the same day"** promise for
  non-technical founders.
- Preserve **founder control**: money, data access, and irreversible calls stay
  gated by Galaxia governance regardless of which runtime executes.

## Non-goals

- Rewriting the onboarding generator (mission → objectives → org). That is the
  crown jewel and stays.
- Ripping out `NativeBackend` in one step. It becomes the default *client* of the
  new API (see [§5](#5-runtime-binding-preserving-the-same-day-promise)).
- Building our own agent harness features (better memory, tool discovery, etc.).
  The opposite: we delete that surface over time.

## 1. The reframe

```
        ┌──────────────────────── GALAXIA (control plane) ────────────────────────┐
        │  mission→org generator · objectives/KRs · initiative queue · governance   │
        │  budget envelopes · decisions/approvals · institutional memory · tenancy   │
        │                Business-Function MCP server / API  (per-tenant)            │
        └──────▲────────────────────────▲────────────────────────▲─────────────────┘
               │ bind: internal          │ bind: external          │ bind: human
    ┌──────────┴─────────┐   ┌───────────┴──────────┐   ┌──────────┴───────────┐
    │ Internal agent      │   │ External agent        │   │ Human                 │
    │ managed OpenClaw     │   │ founder's OpenClaw /  │   │ person in Slack /     │
    │ Gateway / Native     │   │ Claude Code (MCP)     │   │ app; same loop        │
    └─────────────────────┘   └───────────────────────┘   └───────────────────────┘
                  one function slot · three interchangeable worker bindings
```

Galaxia becomes an **MCP server / API** (the inverse of today, where it is an MCP
*client*). Workers bring their own reasoning, tools, connectors, and how-to memory.
Galaxia owns what to work on, who owns it, what it costs, what's allowed, what's
true, and what the company has learned.

## 1a. Worker bindings — the hybrid workforce

The generated org is a set of **function slots**. Each slot is worker-agnostic and
bound to one (or a mix) of three worker types. The binding can change over time —
staff a function with a human today, an agent tomorrow — without touching the org
design or the objectives.

| Binding | Who/what | Transport + identity | Serves |
|---|---|---|---|
| **Internal agent** | Galaxia's managed runtime (managed OpenClaw Gateway persona; `NativeBackend` transitionally) | service call / MCP; service identity | zero-setup, same-day default |
| **External agent** | the founder's own OpenClaw / Claude Code | MCP (streamable-HTTP) + per-function token | BYO-capabilities; import-existing-business |
| **Human** | a person in the role | UI / channel (Slack/WhatsApp/app) + user account | mixed teams; human-run functions |

All three hit the **identical Business-Function interface** ([§2](#2-the-business-function-mcp-surface)) —
`get_mandate`, `get_next_initiative`, `report_result`, `request_decision`,
`coordinate_with`. Only transport + identity differ. A slot may be **mixed** (a
human lead with agent ICs) and workers **coordinate with each other through the
same channels + mission log** regardless of type (OpenClaw's ~25 messaging
channels make mixed human+agent threads native).

Two consequences fall out of admitting humans and scheduled agents as workers:

- **The lifecycle must be async-first.** A human or a scheduled agent can't be
  `run()`-and-awaited synchronously. Initiatives move
  `offered → claimed → in-progress → reported → audited`, with timeouts and
  reassignment. Synchronous push (a backend that calls a worker and blocks) becomes
  an *optimization for internal agents only* — so **pull/connected is the primary
  posture**, push an internal fast-path. (See [§3](#3-the-agentbackend-seam-already-supports-this).)
- **The human binding is the founder-in-the-loop machinery, generalized.** We
  already model a human (the founder) participating via decisions/approvals; a
  human *worker* is the same machinery promoted from "approver" to "does the
  initiative." And the governance reputation signals (trust, accuracy, ROI,
  reliability — already per-agent) become **staffing-agnostic**: they rate humans
  and external agents too.

## 2. The Business-Function MCP surface

A small, powerful toolset served by Galaxia to a connected agent. Names are
illustrative; the shape is the point.

| Tool | Purpose |
|---|---|
| `get_mandate()` | "You are the **Growth** function for Company X." Mission, your objectives + KRs, budget envelope, constraints, brand, current metrics. |
| `get_next_initiative()` | The next prioritized initiative for your function (with its budget envelope + acceptance criteria). |
| `report_result(initiative, outcome, artifacts, spend)` | Close the loop; Galaxia updates state, records spend, routes to audit. |
| `get_business_state()` | Current state of the company + your function. |
| `coordinate_with(function, message)` / `post_update(text)` | Cross-function messaging + the founder-facing mission log. |
| `request_decision(kind, payload)` / `request_budget(cents, reason)` | Escalate to the founder. **Governance & budget stay in Galaxia.** |
| `record_metric(...)` / `write_institutional_memory(...)` | Durable, cross-agent business memory + KR telemetry. |

These map onto services that already exist: `services/objectives.py`,
`services/runs.py` (initiatives/tasks), `services/budget.py` +
`runtime/cost_meter.py`, `services/decisions.py`, `services/governance.py`,
`services/memory.py`. The MCP server is a **new transport over existing business
logic**, not new business logic.

## 3. The `AgentBackend` seam already supports this

`runtime/backends/__init__.py` defines:

```python
class AgentBackend(Protocol):
    async def run(self, ctx: RuntimeContext, agent: Agent, task: Task) -> dict: ...

def get_backend(backend_type: str) -> AgentBackend: ...
```

There are **already two implementations**: `NativeBackend` (in-process loop) and
`MarketplaceBackend`, which "runs a *hired* agent … the remote execution itself
[happens elsewhere] while the org chart treats hired agents identically." So
**"execution happens outside Galaxia" is already a supported shape.** This RFC
adds a third backend — call it `ConnectedBackend` — whose `run()` doesn't execute
a loop at all: it **offers the initiative** to the bound worker and awaits a
`report_result`.

**Two integration postures (they compose):**

- **Push / orchestrated** — `ConnectedBackend.run()` invokes a worker for a task
  and collects the result (e.g. `openclaw agent --agent <function> --json`). This
  is *"just swap the backend implementation"* — the fastest on-ramp, and it already
  deletes the native loop. Best for **internal agents**.
- **Pull / connected** — the worker wakes on its own cadence (cron / a human
  opening their app), **pulls** `get_next_initiative()` over MCP, and reports back.
  Required for **humans and scheduled external agents**, and the thing that unlocks
  BYO-agents + import-existing-business.

Because a human or scheduled agent can't be awaited synchronously, the lifecycle is
**async-first** — *offered → claimed → in-progress → reported → audited* with
timeouts/reassignment — and **pull is the primary posture**; push is an internal
fast-path over the same MCP surface.

**Unit of deployment: a persona, not a process.** For internal agents on OpenClaw,
"spin up OpenClaw per agent" means **one managed Gateway hosting one persistent
persona per function** (each with its own workspace/memory/model), and a task is a
*run* against that persona — not a fresh process per task. This is a step up from
today's per-task native memory.

## 4. Capability brokering & the budget model (the load-bearing decision)

Today `CostMeter` (`runtime/cost_meter.py`) reserves budget **before every LLM
token** and every external charge — a hard chokepoint. If agents run on their own
runtime with their own provider keys, **Galaxia never sees those tokens**, so
per-token metering goes away. Budget enforcement moves up a level:

- **Initiative-level envelopes.** Each `get_next_initiative()` carries a spend
  cap; the agent works within it and returns `spend` in `report_result`.
- **Broker only money-touching capabilities.** Keep Galaxia-brokered (and
  metered) the things that spend real external money — media generation, ads,
  domains, paid data — via the existing `metered_external` path. Let the rest
  (files, web, generic tools) be the agent's own.
- **Audited self-report.** Reported spend is reconciled against brokered charges
  and the governance reputation signal; large or anomalous self-reports escalate.

**Decision required:** we trade a token-level chokepoint for a cleaner
architecture and a coarser (envelope-level) budget guarantee. This also answers
the earlier "capability brokering" question: *money-touching capabilities stay
Galaxia-brokered; everything else is the agent's.*

## 5. Worker binding — preserving the "same-day" promise

Three worker types ([§1a](#1a-worker-bindings--the-hybrid-workforce)), one
protocol:

- **Internal agent (zero setup):** Galaxia provides a **default hosted runtime**
  that auto-binds to the function slots — a **managed OpenClaw Gateway** (or,
  transitionally, today's `NativeBackend`). Batteries included; the non-technical
  founder's same-day path.
- **External agent (power user / existing business):** point your own OpenClaw /
  Claude Code agent at the same Galaxia MCP endpoint with a per-function token.
- **Human (mixed teams / human-run functions):** a person claims initiatives and
  reports results through a UI or a messaging channel (Slack/WhatsApp/app) tied to
  their user account — the same mandate/initiative/report loop, rendered for a
  human. This is the **import-existing-business** on-ramp: existing people bind to
  function slots and get the objectives/governance/coordination layer over how they
  already work, then hand functions to agents as trust builds.

The key move that protects the same-day promise: **the built-in runtime is just
the first, most-tested client of the same Business-Function API** — we dogfood our
own protocol. If it's awkward for us, it's awkward for every worker type.

## 6. Multi-tenancy

OpenClaw isolates at the **persona/workspace** level within one Gateway — not a
company boundary. Tenancy stays Galaxia's responsibility.

**Invariant: worker identity is `(company, function)`, never `function` alone.**
Two businesses that both have a "Growth" function are **two distinct agents**, not
one shared persona. "Growth" is a role *type*, not an identity. Concretely
`agentId = <company_id>:growth`, with its own OpenClaw `agentDir`/workspace/session
store (the OpenClaw docs explicitly warn never to reuse `agentDir`). Reusing one
running agent across tenants would leak the first company's workspace, memory, and
session history into the second — the classic multi-tenant failure. So the same
*role* across N businesses is N isolated agents.

Two isolation layers, both keyed on tenant:

- **Business data (Galaxia side):** the MCP server is **per-tenant scoped** by the
  connection token; every tool call is authorized against `(company, function)` +
  RLS. Mandate/initiatives/institutional memory can't cross tenants *even if a
  runtime were shared* — this layer holds regardless.
- **Runtime state (worker side):** the agent's own workspace / how-to memory /
  sessions are isolated by the distinct `agentId`/`agentDir` **and** by running
  **Gateway-per-tenant** (or a pool with strict per-agent workspace isolation).
  External agents are inherently the founder's own boundary.

**Reusable persona = template, not instance.** A standard "Growth agent"
definition (or a marketplace agent) reused across businesses is a **shared template
instantiated per-company** — exactly the existing `MarketplaceBackend` "hired
agent" pattern (one catalog definition, an isolated instance per company). The
*definition* is reusable; the *running agent* is always per-`(company, function)`.

## 7. Reference runtime: OpenClaw

Full scoping in the appendix. Summary of fit against Job B:

| Need | OpenClaw | Evidence |
|---|---|---|
| MCP **client** → our remote server | ✅ `mcp.servers.<name>`, **streamable-HTTP/SSE/stdio**, bearer/OAuth/mTLS, per-agent routing | docs `/cli/mcp` |
| Headless / worker drive | ✅ `openclaw agent --json`, `POST /v1/chat/completions`, `POST /hooks/agent` | docs `/cli/agent`, `/gateway/openai-http-api` |
| Scheduling = "check-in" model | ✅ cron + `isolated` runs + **`webhook` result delivery** | docs `/automation/cron-jobs` |
| Memory | ✅ per-agent Markdown + vector `memory_search`, pluggable backends | docs `/concepts/memory` |
| Multi-agent identity | ✅ agent = persona scope (workspace/model/sessions/sandbox) + `bindings` | docs `/concepts/multi-agent` |
| BYOK providers + failover | ✅ Anthropic/OpenAI/Gemini/local + ~30 more, auth-profile rotation | docs `/concepts/model-providers` |

**What it brings beyond plumbing:** a skills/ClawHub + plugin-SDK ecosystem;
~25 messaging channels with routing (a founder DM to "the marketing agent" becomes
trivial); sandboxing + provider failover + operational HITL/tool-policy.

**Confirmed gaps = our layer:** no OKRs/mandate model, **no native budget
metering/enforcement** (open issue #58826), no business-level approval/governance,
no org design, no cross-agent institutional memory, isolation ≠ multi-tenancy.
Exactly the split this RFC relies on.

**Risks:** (1) validate the MCP-tool→model path inside an *embedded* OpenClaw
turn before committing; (2) multi-tenancy is Gateway-per-tenant; (3) we take on
Gateway lifecycle + version churn of a large, fast-moving monorepo.

## 8. Migration plan (incremental)

1. **Define the Business-Function MCP surface** ([§2](#2-the-business-function-mcp-surface))
   as a first-class server over existing services. No user-visible change.
   **✅ Done** — `services/business_function.py` (the worker-agnostic surface) +
   `api/bf_mcp.py` (the MCP transport).
2. **Re-point `NativeBackend` to consume that API** instead of reaching into
   services directly. Proves the protocol against our own runtime. **✅ Done** —
   the native loop assembles its mandate from `business_function.get_mandate`.
3. **Make the initiative lifecycle async-first** (*offered → claimed →
   in-progress → reported → audited* with timeouts/reassignment) so a slow worker
   (human or scheduled agent) is a first-class case, not an exception. **✅ Done** —
   `claim_initiative` (atomic) + a claim lease (`tasks.lease_expires_at`) reaped by
   `release_expired_claims` on a cron.
4. **Add `ConnectedBackend`** + a "connect your own agent" flow (per-function
   token + a template OpenClaw/Claude Code config). First external function goes
   live behind a flag. **✅ Done** — `runtime/backends/connected.py`, the founder
   runtime switch, and the mint-a-connection-token UX (off until a secret/Gateway
   is configured).
5. **Ship the managed OpenClaw Gateway** as the default internal-agent runtime;
   make it the batteries-included binding. **✅ In-repo half done** — the default
   binding is configurable (`ABOS_DEFAULT_AGENT_BACKEND`, auto-binding generated
   functions to the connected runtime when a Gateway is set) and the persona
   identity is per-tenant (`agentId = <company_id>:<function>`, [§6](#6-multi-tenancy)).
   Standing up the Gateway *service* is deployment infra, not code.
6. **Add the human binding** — a UI/channel surface where a person claims and
   reports initiatives for a function (reuses the async lifecycle from step 3 and
   the existing membership/decision machinery). Unlocks mixed teams +
   import-existing-business. **✅ Done** — the `human` runtime + the user-authenticated
   human-worker surface (`api/human_worker.py`) + the org-page "My work" panel.
7. **Thin the core:** migrate capability tools out to worker-side; keep only
   business-state tools in Galaxia. Retire the in-house discovery/compaction
   surface. **◻ Surface complete; deletion staged.** The Business-Function surface
   now exposes the full [§2](#2-the-business-function-mcp-surface) toolset
   (mandate, initiative lifecycle, `get_business_state`, `record_metric`,
   `write_institutional_memory`, `post_update`, `request_decision`,
   `request_budget`) — a connected worker reaches parity with the native loop, the
   prerequisite to thinning. Per the [non-goals](#non-goals), the native tool
   surface is **not** ripped out in one step: it stays the default while the
   connected path is proven, and its capability tools retire *over time*. The
   **capability split** is now explicit (see below): money-touching capabilities
   stay Galaxia-brokered; everything else is the worker's own.

Each step is shippable and reversible; no big-bang cutover.

**The capability split (the boundary step 7 draws).** Business-state and
governance tools live in Galaxia and are exposed over the Business-Function surface
to *every* worker binding — mandate, initiatives, metrics, institutional memory,
mission-log updates, and founder escalations (`request_decision` / `request_budget`,
which only *raise* a decision; Galaxia + the founder resolve it, [§9](#9-security-considerations)).
Money-touching capabilities (media generation, ads, domains, paid data) stay
**Galaxia-brokered and metered** via the existing `metered_external` path
([§4](#4-capability-brokering--the-budget-model-the-load-bearing-decision)).
Everything else — files, web, generic tools, the think→act loop, tool discovery,
context compaction — is the **worker's own**, and the native loop's in-house
versions of those retire as the connected runtime becomes the default.

## 9. Security considerations

- **Per-function tokens** are tenant-scoped credentials; every MCP tool call is
  authorized against `(company, function)` + RLS. Token compromise is blast-radius
  limited to one function of one company.
- **The BYOK secret boundary is unchanged** for anything Galaxia still brokers
  (envelope encryption per `MISSION.md`). Agent-owned provider keys leave our
  custody entirely — a *reduction* in secrets we hold.
- **Governance is enforced server-side**, never in the worker: a worker can
  `request_decision`, but only Galaxia (and the founder) can resolve one — true for
  internal agents, external agents, and humans alike.
- **Human workers authenticate as users** (account + company membership), not
  per-function service tokens; their initiative claims and reports are attributed
  and audited the same way, and count toward the same governance reputation.

## 10. Open questions / decisions needed

1. **Budget guarantee** — accept envelope-level enforcement + audited self-report
   in exchange for losing the token-level chokepoint? ([§4](#4-capability-brokering--the-budget-model-the-load-bearing-decision))
2. **Protocol surface** — MCP-only, or also a plain REST/webhook API for runtimes
   that don't speak MCP? (MCP-first recommended; OpenClaw + Claude Code both speak
   it.) The **human** binding needs a UI/channel surface regardless.
3. **Default internal runtime** — managed OpenClaw Gateway from the start, or keep
   `NativeBackend` as the default until the OpenClaw path is proven?
4. **Multi-tenant model for the managed runtime** — Gateway-per-tenant vs
   pool-with-workspace-isolation.
5. **How much of the human binding ships in v1** — full parity (a human can staff
   any function) vs. humans only as approvers/leads at first, with agent ICs doing
   the execution.

## 11. Alternatives considered

- **Keep and invest in `NativeBackend`.** Rejected: it's the undifferentiated
  treadmill; we lose ground weekly and it's the source of most recent bugs.
- **Adopt a different runtime (Claude Code / Codex) as primary.** Not exclusive —
  the MCP contract is runtime-agnostic; OpenClaw is the *reference* because it's
  MIT, self-hostable as a Gateway service, MCP-native, and multi-agent. Claude
  Code remains a first-class client for power users.
- **Embed Galaxia as an OpenClaw plugin** (rather than an external MCP server).
  Rejected: the plugin SDK "assumes hosted Gateway infrastructure" and would
  invert ownership; keeping Galaxia as the control plane the agent connects *out*
  to preserves the tenancy/governance boundary.

## Appendix: OpenClaw evaluation sources

- MCP client / transports / auth — `docs.openclaw.ai/cli/mcp`
- Headless agent drive — `docs.openclaw.ai/cli/agent`,
  `docs.openclaw.ai/gateway/openai-http-api`
- Scheduling / webhooks — `docs.openclaw.ai/automation/cron-jobs`
- Memory — `docs.openclaw.ai/concepts/memory`
- Multi-agent — `docs.openclaw.ai/concepts/multi-agent`
- Providers / failover — `docs.openclaw.ai/concepts/model-providers`
- Budget gap — `github.com/openclaw/openclaw/issues/58826`
- License — MIT (`github.com/openclaw/openclaw`)
