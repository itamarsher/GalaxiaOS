# Galaxia — full-dogfooding gap analysis

> **Architecture update (2026-07): "Galaxia" is now a real, founder-owned company,
> not a synthetic bootstrap.** The old startup bootstrap that provisioned a fixed
> `founder@galaxia.abos` user + fixed company id at boot has been removed, along
> with the user-id promoter gate and `POST /dev/galaxia/reset`. Instead: real user
> registration (Google SSO by default, email/password fallback), and the **first
> company onboarded** in a deployment is flagged `is_platform=True`
> (`services/platform_company.py`). That flag — not a hard-coded founder id — is
> what authorizes the promoter tools, the global Render key, and the platform cron
> jobs, so it survives an ownership transfer. Google Drive is now connected
> **account-wide** (per user) so every business a founder launches files into the
> same Drive. Everything below that refers to "Galaxia the bootstrapped company"
> should be read as "the platform company (the founder's first)".

> *Galaxia* is the reference business a founder spins up on ABOS whose **mission is to
> build and operate ABOS itself**. If Galaxia can run fully agentically — turning its own
> agents' unmet needs into shipped code and a live deploy, with the founder only touching
> genuinely founder-level decisions — then every founder on the planet can run their own
> business the same way. Galaxia is the proof: ABOS building ABOS.

This document maps the self-improvement loop the vision requires, states which rungs already
exist in the codebase, and enumerates exactly what is missing to close it. It is a gap
analysis, not an implementation.

## The loop we are trying to close

```
  any agent in any company hits a limitation
        │  report_bug / request_capability
        ▼
  ┌─────────────────────────┐
  │ feature-request backlog │  cross-company, deduped, one vote per (company,user)
  └─────────────────────────┘  app/services/feature_requests.py                     ✅ EXISTS
        │  (Galaxia's Platform agent) list_feature_requests → promote_feature_request
        ▼
  GitHub issue (label: bug | enhancement)  app/integrations/issues.py               ✅ EXISTS
        │  on: issues opened
        ▼
  issue-triage.yml  → close, or post "## Implementation notes" + label claude-implement  ✅ EXISTS
        │  on: label claude-implement
        ▼
  issue-implement.yml → branch + PR "Closes #N" + `uv run pytest`                    ✅ EXISTS
        │  on: pull_request
        ▼
  ci.yml → ruff · provider-guard · alembic upgrade · pytest · tsc · next build       ✅ EXISTS
        │
        ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │  PR APPROVAL + MERGE                                                        │  ❌ MISSING — human gate
  │  "The PR is gated by CI + human review — nothing lands automatically."      │  (issue-implement.yml)
  └───────────────────────────────────────────────────────────────────────────┘
        │  push to claude/abos-system-architecture-u9xny4
        ▼
  ci.yml deploy job → Render deploy hooks (preDeploy: alembic upgrade head)         ⚠️ EXISTS, no-op until
        │                                                                             hooks+token configured
        ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │  POST-DEPLOY VERIFY + ROLLBACK, then mark the backlog entry delivered and   │  ❌ MISSING
  │  tell the agents/companies who asked that their capability now exists       │
  └───────────────────────────────────────────────────────────────────────────┘
```

The rungs from *demand* through *CI* are built. The loop is **open at three joints**: it is
never **bootstrapped** (no Galaxia company exists to drive it), it is never **merged/deployed**
without a human, and it never **closes back** onto the requesters. Details below.

## What already exists (the built rungs)

- **Cross-company demand backlog** — `report_bug` / `request_capability` (any agent) and the
  founder/copilot path both land in one deduped, voted backlog
  (`feature_requests.py`, `platform_requests.py`).
- **Promoter tools** — `list_feature_requests` / `promote_feature_request`, gated to the abos
  admin company, file real GitHub issues with demand attribution (`runtime/tools/platform.py`).
- **GitHub issue seam** — real REST adapter with title-dedup and "+1" demand counting
  (`integrations/issues.py`); default repo `itamarsher/just-launch-it`.
- **Triage → implement workflows** — `issue-triage.yml` (investigate → close or label) and
  `issue-implement.yml` (implement on a branch, open a PR, run tests).
- **CI** — `ci.yml` runs lint, the provider-boundary guard, the full Alembic chain against
  pgvector, pytest, and the frontend `tsc`/`build`.
- **Deploy scaffolding** — a `deploy` job wired to Render deploy hooks with `alembic upgrade
  head` in preDeploy (`ci.yml`, `docs/deploy.md`, `render.yaml`).
- **Founder escalation surface** — a governance policy engine (`services/governance.py`) and a
  founder **decision inbox** (`DecisionRequest`, `api/decisions.py`) where `require_approval`
  actions block until the founder answers. This is the boundary the vision wants to preserve.
- **Codebase read tools** — every agent can read this repo (`list_repo_files` / `read_repo_file`)
  so the Platform agent can investigate bugs against real source.

## The gaps

Prioritised P0 (loop cannot run without it) → P2 (hardening).

### P0-1 — the loop needs a driving company — ✅ RESOLVED (now via a real company)

> **Status: done, then re-architected (2026-07).** Originally solved by a startup
> bootstrap (`app/services/galaxia.py`) that synthesized a fixed founder + company.
> That bootstrap has since been **removed** in favour of a real, founder-owned
> company: the first company onboarded is flagged `is_platform=True`
> (`services/platform_company.py`), and the promoter gate (`_is_abos_admin_company`
> in `runtime/tools/platform.py`) authorizes off that flag instead of a hard-coded
> user id. Covered by `tests/test_platform_company.py`. The rest of this section is
> the original analysis, retained for history.

`ABOS_FEATURE_ADMIN_USER_ID = "91da8f48-…"` is hardcoded in `runtime/tools/platform.py`, and the
promoter tools authorize by checking that this user is a member of the acting company
(`_is_abos_admin_company`). But **nothing in the codebase ever creates that user, a Galaxia
company owned by them, its fleet, or its mission.** `api/dev.py` seeds only a generic
`dev@abos.local` account and is explicitly "remove before going live."

Consequence: in any real deployment, no company has a membership for `91da8f48-…`, so
`list_feature_requests` / `promote_feature_request` refuse everywhere → the backlog never
becomes issues → **the entire loop never starts.** This is the single biggest blocker.

**Recommendation:** a deterministic, production-safe bootstrap (an idempotent startup task or a
data migration, not the dev router) that provisions the Galaxia founder user (id
`91da8f48-…`), a Galaxia company owned by them, the standard fleet (which already guarantees a
Platform agent — `onboarding.py:_fleet_specs`), and a mission of "build and operate ABOS."
Derive the id/email from config so it is not a magic literal split across two files.

### P0-2 — Nothing schedules the promoter, and the Platform agent doesn't know it exists — ✅ IMPLEMENTED

> **Status: done.** A `promote_feature_backlog` cron (`app/jobs/scheduled.py`, registered in
> `app/runtime/worker.py`) drains the shared backlog into tracker issues on Galaxia's behalf,
> hourly, above a configurable demand threshold. The filing logic is the new shared
> `app/services/promoter.py` (`promote_request` / `promote_backlog`), which the Platform agent's
> `promote_feature_request` tool now also calls, so interactive and scheduled promotion behave
> identically. Runs unscoped (the backlog is cross-company). Covered by `tests/test_promoter.py`.

The Platform agent is **DORMANT by default** — its role prompt says "the CEO never dispatches
you … you wake ONLY when another agent triggers you" and instructs it to file with `open_issue`.
It is **never told about `list_feature_requests` / `promote_feature_request`**, and no cron or
objective ever wakes Galaxia's Platform agent to drain the backlog. `run_business_cycle`
(`jobs/scheduled.py`) kicks a generic run per active company but carries no directive to review
demand and promote it.

Consequence: even with P0-1 fixed, accrued demand sits in the backlog forever because no
scheduled actor promotes it into issues.

**Recommendation:** a scheduled "platform triage" objective/cron scoped to Galaxia that wakes its
Platform agent to `list_feature_requests` above a demand threshold and `promote_feature_request`
the top entries; and a Galaxia-specific Platform prompt/playbook that documents the promoter
tools and the promote-when-demand-crosses-N policy.

### P0-3 — PR approval + merge is not automated (the explicitly-requested gap) — ✅ IMPLEMENTED

> **Status: done (code); requires GitHub-side config to activate.** `.github/workflows/auto-merge.yml`
> reviews eligible agent PRs and merges them (gated on CI completing green, no branch protection
> required — the workflow is the gate); `.github/dogfooding.yml` encodes the
> escalation boundary + guardrails it consults. Activating it needs branch protection + secrets
> (operator-side, not code) — see `docs/DOGFOODING_OPERATIONS.md`. The reviewer escalates any PR
> touching the founder surface and honours a kill switch + daily merge cap.

`issue-implement.yml` states outright: *"The PR is gated by CI + human review — nothing lands on
the default branch automatically."* There is no auto-review workflow, no `enable_pr_auto_merge`,
no automated approval anywhere in `.github/workflows/`.

**Recommendation:** an auto-merge workflow that, for an **agent-authored** PR (label/author
allow-list only) with **green required CI**, runs an automated reviewer agent and, on approval,
approves + merges — with a **risk classifier** that routes founder-level changes to the decision
inbox instead of merging (see the escalation boundary below). Pair it with a GitHub **branch
protection ruleset** that requires the CI checks + one approving review, so the *only* path to
the default branch is green CI plus the reviewer agent's approval — the automation cannot be
bypassed and neither can a human sneak past CI.

### P1-4 — Merge → deploy → verify is not closed; no post-deploy gate or rollback — ◑ PARTIAL

> **Status: partial.** `ci.yml` now has a post-deploy health gate that fails the deploy job if the
> API doesn't come back healthy (no-op until `ABOS_HEALTHCHECK_URL` is set). Revision-aware
> verification + automated rollback (needs the Render API) and feeding deploy status back into
> Galaxia's memory remain — tracked in `docs/DOGFOODING_OPERATIONS.md`.

The deploy job fires on push to `claude/abos-system-architecture-u9xny4` (which auto-merge would
trigger), but: (a) it is a **no-op until `RENDER_DEPLOY_HOOK_*` and the app-side
`ABOS_GITHUB_TOKEN` are configured** — `get_issue_tracker()` returns `None` with no token, so a
tokenless prod also can't file issues; (b) there is **no smoke test / `/health/ready` gate after
deploy and no automated rollback** if the new revision is unhealthy; (c) deploy status is never
fed back to Galaxia, so the fleet can't observe whether its own change shipped.

**Recommendation:** a post-deploy health gate (poll `/health/ready`, fail the release and roll
back on error) and a hook that records deploy success/failure into Galaxia's company memory so
the loop is observable to the agents that drove it.

### P1-5 — The loop never closes back onto the requesters — ✅ IMPLEMENTED

> **Status: done.** A `reconcile_delivered_requests` cron (`promoter.reconcile_delivered`) polls
> each promoted entry's tracker issue and, once it is closed (fix merged), flips the entry to a new
> `delivered` state and writes a "your requested capability shipped" notice into each requesting
> company's memory. Covered by `tests/test_promoter.py`.

`mark_promoted` records the issue number, but when the PR merges and the issue closes,
**nothing** flips the `FeatureRequest` to a delivered state, and the companies/agents who
requested the capability are **never notified that it now exists.** Agents keep re-requesting a
gap that has already been closed and never learn otherwise.

**Recommendation:** an issue-closed-by-merge signal (webhook or reconciliation cron) that marks
the backlog entry `delivered`, links the merged PR, and notifies the requesting companies (and
ideally surfaces the new capability to their agents). Without this the loop is a ratchet with no
feedback — the whole point of dogfooding demand.

### P1-6 — A shipped capability isn't guaranteed to become a usable tool — ◑ PARTIAL

> **Status: partial (convention, enforced by review).** The capability-PR acceptance convention
> (register the tool + add a test that exercises it + keep scope) is documented in
> `docs/DOGFOODING_OPERATIONS.md` and the auto-merge reviewer checks for it. A hard CI gate that
> mechanically fails an unregistered/untested capability PR is the remaining step.

When a `request_capability` ships as code, an agent only gains the capability if the PR also
registers the new tool in the runtime tool registry **and** the worker restarts to pick it up.
Nothing enforces that a promoted capability's PR includes tool registration + a test proving the
requested capability now exists.

**Recommendation:** an acceptance convention for capability PRs (must register the tool and add a
test that exercises it) enforced in the reviewer agent's checklist and/or CI, so the loop is
verifiably self-extending rather than shipping dead code.

### P2-7 — No meta-loop safety rails / kill switch — ✅ IMPLEMENTED

> **Status: done.** `.github/dogfooding.yml` provides a kill switch (`auto_merge.enabled` +
> the `DOGFOODING_AUTOMERGE` repo variable), a daily merge cap (`max_merges_per_day`), and a veto
> window (`veto_window_minutes`), all enforced by the auto-merge workflow; PR comments + GitHub's
> merge history are the audit trail. Kill-switch ladder documented in `docs/DOGFOODING_OPERATIONS.md`.

A repo that merges its own code and deploys itself needs guardrails distinct from the runtime
circuit breakers (which govern *agent* actions, not *the pipeline*): a global kill switch for
auto-merge, a cap on merges/deploys per day, a founder veto window before a merged change
deploys, and an audit trail of every autonomous merge. None of these exist for the pipeline.

**Recommendation:** a small pipeline-guardrail layer — kill switch (a repo variable the workflow
checks), a daily auto-merge budget, and a configurable veto window — plus an append-only audit of
autonomous merges surfaced in the founder dashboard.

### P2-8 — Secrets & permissions for a self-driving repo aren't provisioned/documented as a set — ✅ IMPLEMENTED

> **Status: done (runbook).** `docs/DOGFOODING_OPERATIONS.md` lists the full secret + repo-variable
> + branch-protection set and the state each must be in, as a one-time checklist. Provisioning the
> actual secrets/protection is operator-side (can't be done from the repo).

The loop needs, together: `CLAUDE_CODE_OAUTH_TOKEN` (present in workflows), a merge-capable bot
identity that branch protection permits, the app-side `ABOS_GITHUB_TOKEN` for issue filing, and
the `RENDER_DEPLOY_HOOK_*` secrets. Today these are scattered across the workflows, `config.py`
defaults, and `docs/deploy.md`, and several default to empty/no-op.

**Recommendation:** one "autonomous operation" runbook that lists the full secret + branch-
protection set and the exact state each must be in for the loop to run end-to-end, so standing it
up is a checklist, not an archaeology exercise.

## The founder-escalation boundary

The vision keeps the founder as a board member, not an operator: everything is agentic **except
normal founder-escalated decisions.** ABOS already has the surface for this — the governance
policy engine and the `DecisionRequest` inbox. What is missing is a **defined risk boundary for
code/pipeline decisions** (today the policy engine only classifies *runtime* actions like spend
and external comms, not PRs). A workable default boundary:

| Auto-merge (agentic) | Escalate to founder decision inbox |
|---|---|
| Bug fixes, capability additions, docs, tests, deps within policy | Changes to auth / crypto / tenant-isolation (RLS) |
| Changes with green required CI and a clean reviewer-agent pass | Schema migrations that drop/rewrite data |
| Additive tool registrations behind existing seams | Budget/`CostMeter` or governance-engine changes |
| | Anything touching real-money spend paths (Stripe issuing/link) |
| | A reviewer-agent "uncertain / high-risk" verdict |

Encoding this as a policy the auto-merge workflow consults — rather than hardcoding paths in YAML
— keeps the boundary auditable and lets Galaxia's founder tune it, exactly like the existing
`require_approval` policies.

## Suggested build order

1. **P0-1 Galaxia bootstrap** — nothing runs until the driving company exists. ✅ **done**
   (`app/services/galaxia.py`).
2. **P0-2 Scheduled promoter** — turn standing demand into issues without a human prompt. ✅ **done**
3. **P0-3 Auto-review + auto-merge** with the escalation boundary — the headline gap. ✅ **done**
   (code; needs branch protection + secrets to activate).
4. **P1-4 Post-deploy verify/rollback** + deploy-status feedback into Galaxia. ◑ **partial**
   (health gate shipped; revision-aware rollback + memory feedback remain).
5. **P1-5 Close the loop** — mark delivered + notify requesters. ✅ **done**
6. **P1-6 Capability-PR acceptance convention** — self-extension is verifiable. ◑ **partial**
   (convention + reviewer check shipped; hard CI gate remains).
7. **P2-7/8 Guardrails + secrets runbook** — make it safe and reproducible to operate. ✅ **done**

**Where we are now:** with P0-1/2/3 done, Galaxia runs a fully agentic demand→ship cycle end to
end once the GitHub-side config in `docs/DOGFOODING_OPERATIONS.md` is applied; P1-5 makes it
self-terminating (no re-requesting shipped work); P2-7/8 make it safe to leave running. The
remaining open edges are both in P1-4/P1-6: **revision-aware deploy rollback**, **deploy-status
feedback into Galaxia's memory**, and a **hard CI gate for capability PRs** — all tracked in the
operations runbook.
