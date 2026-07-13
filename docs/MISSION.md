# Mission

**Make owning an autonomous business a right, not a privilege.**

GalaxiaOS is a free, open-source operating system that lets any person on the
planet stand up and run a real company operated by a fleet of AI agents — a CEO
and the functions a business actually needs (growth, research, product, finance,
governance, and more) — under a hard budget and a governance layer, with the
founder acting as a **board member, not an operator**.

A business has always required scarce things: capital, a team, operational
expertise, and the time to coordinate all three. Most people who could run a
great company never get the chance — not for lack of ideas, but for lack of
access. GalaxiaOS exists to remove that barrier. A founder defines a
**Mission**, **Constraints**, and a **Budget**; GalaxiaOS *designs the company
to fit that mission* — generating a fleet whose roles, responsibilities, and
budgets are derived from what this specific business needs, not stamped from a
fixed template. One mission needs a heavy growth function; another, deep research
or product work. The fleet is generated, and it keeps reshaping itself as the
business and its objectives evolve. The goal is simple: *what's your mission,
what's your budget, launch* — everything else is generated.

We win when a non-technical person, anywhere, can describe a mission and a budget
and have a functioning, self-improving business running **the same day**.

## Who we serve

Aspiring and solo founders, indie hackers, and small teams worldwide who have
ideas and intent but not the capital, headcount, or technical depth to operate a
company — **especially the people a paid gatekeeper would exclude**. Owning or
creating an autonomous business must never depend on a subscription or someone
else's permission.

## We dogfood our own product

Our business is to build and operate GalaxiaOS itself. **GalaxiaOS runs as a
company on GalaxiaOS**: exactly one real, founder-owned company carries the
`is_platform` flag (`services/platform_company.py`), and the same agent fleet
every founder gets operates our own roadmap, growth, research, finance, and
governance. That flag is durable state on the company row — it survives process
restarts, redeploys, ownership transfers, and a founder-facing company reset — so
the loop below never silently stops after a bounce.

This is not a slogan; it is a working feedback loop already wired into the code:

```
any agent (ours, or any company's) hits a limitation
      │  report_bug / request_capability
      ▼
cross-company feature-request backlog        (services/feature_requests.py)
      │  the Platform agent / hourly promoter cron
      ▼
tracker issue  (bug | enhancement)           (integrations/issues.py)
      │  issue-triage → issue-implement → CI  (.github/workflows)
      ▼
reviewed, merged, deployed                    (Render deploy hooks)
      │  reconciler cron marks the entry delivered
      ▼
the agents/companies who asked are told their capability now exists
```

When any agent hits a limitation, that unmet need becomes a **demand signal**,
the highest-demand needs are turned into shipped product improvements, and the
platform's own failures escalate the same way (the error monitor forwards any
logged traceback and any failed Render deploy into a deduplicated auto-fix
issue). The only human in the loop is the founder, and only for the decisions a
founder must own: **security, money, data access, and irreversible calls**.
Every founder's friction makes the product better for every founder, and the
platform's capabilities compound as its users' real needs ship continuously.

## Principles

- **Open by default.** The core product is **free and open-source**. Owning or
  creating an autonomous business should not depend on a subscription, a
  gatekeeper, or our permission.
- **Bring your own key (BYOK).** You bring your own model-provider key, stored
  envelope-encrypted (a per-key data key wrapped by the deployment master key).
  You own your compute, your data, and your spend — we never put ourselves
  between you and the model.
- **The founder stays in control.** A hard budget and a governance layer are not
  afterthoughts: every billable action — LLM tokens *and* external charges — is
  metered and reserved before it spends (`CostMeter`), and every outbound action
  can require founder sign-off (`approve_required` autonomy). Autonomy is
  something you grant, not something we take.
- **Future-proof seams.** The system is built around decoupling seams — which
  model vendor answers (`LLMProvider`) and how an agent executes (`AgentBackend`)
  — so the free core never traps you in a single vendor or a single way of
  running agents. Open-source models (Llama, DeepSeek, Qwen, gpt-oss) via any
  OpenAI-compatible host are first-class, not an afterthought.

## The organization the mission generates

The mission text is not decoration — it is the input that *designs the company*.
The generator turns a mission into objectives, and objectives into an agent fleet
(`prompts.MISSION_TO_PLAN_SYSTEM` → `PLAN_TO_ORG_SYSTEM`), and every agent's
prompt is anchored to that mission thereafter. So a sharper mission produces a
sharper org.

**Default fleet (guaranteed oversight + the common functions):** CEO, Growth,
Research, Product, Design, Finance, Auditor, Governance, Data, and a dormant
Platform agent that turns unmet needs into tracker issues. Onboarding backfills
these so every company has the oversight roles; the CEO can request the founder's
approval to hire more as objectives evolve.

### Roles GalaxiaOS itself needs beyond the defaults

Because our own company is an **open-source, self-improving, BYOK platform**, the
default fleet is necessary but not sufficient. These are the roles the platform
company should add — each maps to real seams and tooling that already exist, and
each is a strong candidate to promote into a first-class role for any company
whose mission is *software / a developer platform*:

1. **Engineering Lead (software).** The default Platform agent only *files* the
   issue; today implementation runs through the CI auto-fix pipeline behind a
   human merge gate. An Engineering Lead owns code quality, review, and the
   merge→deploy loop — the difference between "a need was logged" and "the fix
   shipped." This is the role that closes the dogfooding loop end to end.
2. **Security Lead.** Distinct from Governance (safety/compliance/oversight): owns
   the BYOK secret boundary (envelope encryption + master-key custody), free-tier
   abuse screening (`services/screening.py`), dependency/supply-chain risk, and
   vulnerability response. A platform that holds every founder's provider keys
   cannot treat security as a side duty of another role.
3. **Developer Relations / Community Lead.** An open-core project lives or dies on
   its community. Owns external issue/PR triage, contributor onboarding, docs, and
   release notes — and is the human-facing front of the same demand→issue loop for
   people who report needs from outside the platform.
4. **Support / Founder Success Lead.** The mission targets *non-technical*
   founders, so someone must own onboarding help and troubleshooting, and turn
   recurring confusion into `request_capability` signals — making support a source
   of product improvements, not a cost center.
5. **Ecosystem / Marketplace Lead.** Curates the future agent-and-capability
   marketplace and partnerships (named sustainability pillars), leveraging the
   governance system's existing per-agent trust, accuracy, ROI, and reliability
   signals as the marketplace's trust layer.
6. **Legal & Policy Lead.** Owns open-source licensing, ToS, privacy/DPA, and the
   BYOK data-handling policy, grounded in the existing legal tooling
   (`runtime/tools/legal.py`). Necessary the moment real users and real data
   arrive.

## What stays free

The thing that matters most — generating and running a real autonomous business
from a mission and a budget — is the free, open-source, BYOK core. **That is the
product. It does not become a paid tier**, and the core capability is never
paywalled. Self-hosting always stays free.

## How we sustain the open core

Paid, optional features are built *around* the open core rather than gating it:

1. **Hosted / managed convenience** — a run-it-for-you deployment so you don't
   have to operate the infrastructure. You pay to skip the ops, never to unlock
   the product.
2. **Agent-and-capability marketplace** — let anyone publish agents and earn from
   them. (Governance already tracks per-agent trust, accuracy, ROI, and
   reliability — the marketplace's trust signal.)
3. **Importing existing businesses** — bring an already-operating business onto
   GalaxiaOS, not just greenfield launches.
4. **Investing in autonomous businesses** — let people back the businesses others
   have launched.
5. **Support, partnerships & enterprise/compliance features** — the controls
   larger organizations need to run this safely at scale.

These fund the mission; they are not the mission. The mission is to put ownership
and creation of autonomous businesses within reach of *everyone* — free,
open-source, and BYOK, so adoption is unconstrained.
