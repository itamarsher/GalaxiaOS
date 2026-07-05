# Dogfooding operations runbook

How to stand up and safely run Galaxia's fully-autonomous demand→ship loop, and
the guardrails that keep it bounded. Companion to the gap analysis in
[`GALAXIA_DOGFOODING.md`](GALAXIA_DOGFOODING.md) — that doc explains *why* each
piece exists; this one is the *checklist* to operate it.

## The loop, end to end

```
agent hits a gap → feature-request backlog → [cron: promote] → GitHub issue
   → issue-triage → issue-implement (PR) → CI → [auto-merge: review + arm]
   → merge → deploy (Render) → health gate → [cron: reconcile] → backlog "delivered"
   → requesters notified
```

Every hop is automated. The only human touchpoint by design is a PR that lands on
the **founder-escalated surface** (see below), which is routed to a person instead
of merged.

## One-time setup

### 1. Secrets (GitHub repo → Settings → Secrets and variables → Actions)

| Secret | Used by | Purpose |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | triage / implement / auto-merge / claude | the agent identity for all pipeline workflows |
| `RENDER_DEPLOY_HOOK_API` | `ci.yml` deploy | trigger the API release on merge to the default branch |
| `RENDER_DEPLOY_HOOK_WORKER` | `ci.yml` deploy | optional — omit on the free-tier (worker folded into API) |
| `RENDER_DEPLOY_HOOK_WEB` | `ci.yml` deploy | trigger the web release |
| `ABOS_HEALTHCHECK_URL` | `ci.yml` deploy | the API `/health/ready` URL; the post-deploy gate probes it |

App-side (Render service env, not GitHub) — required for the loop's app half:

| Env var | Purpose |
|---|---|
| `ABOS_GITHUB_TOKEN` | the running app files/reads tracker issues; **without it the promoter no-ops** |
| `ABOS_GITHUB_REPO` | defaults to `itamarsher/just-launch-it` |
| `ABOS_MASTER_KEY` | envelope key for BYOK secrets (from a KMS in prod) |

### 2. Repository variables

| Variable | Effect |
|---|---|
| `DOGFOODING_AUTOMERGE` | kill switch. Set to `off` to halt all auto-merges immediately, no commit needed. Missing/anything-else = on. |

### 3. Branch protection (this is what makes auto-merge *safe*)

On the default branch (`claude/abos-system-architecture-u9xny4`), add a ruleset:

- **Require status checks to pass:** the CI jobs (`backend`, `frontend`). This is
  the guarantee that armed auto-merge only completes on green — the workflow
  *arms* the merge, GitHub *withholds* it until checks pass.
- **Require a pull request review before merging:** 1 approval. The auto-merge
  reviewer supplies it for eligible PRs; a founder-escalated PR needs a human's.
- **Do not allow bypassing** the above, so neither the automation nor a human can
  land red or unreviewed code.

Without branch protection the pipeline still works, but "auto-merge" degrades to
"merge as soon as armed" — protection is what enforces the CI gate.

## Guardrails (`.github/dogfooding.yml`)

The auto-merge workflow reads this file on every PR. Tune it — don't edit YAML:

- `auto_merge.enabled` — soft master switch (the repo variable is the hard one).
- `auto_merge.max_merges_per_day` — runaway backstop; over it, PRs escalate.
- `auto_merge.veto_window_minutes` — delay before arming, for a founder to veto.
- `escalate_paths` — the founder-escalated surface (auth, crypto, RLS, migrations,
  budget/CostMeter, governance, real-money paths, the workflows themselves, and
  the bootstrap). A PR touching any of these is labeled `founder-review` and left
  for a human — never auto-merged.

Changing the boundary is a one-line edit to `escalate_paths`; because that file is
itself in `escalate_paths`, loosening the guardrails is itself a founder-reviewed
change.

## Capability-PR acceptance convention (P1-6)

When a `request_capability` ships, the capability only becomes real if the PR
actually wires it in. The auto-merge reviewer enforces, and implement agents should
follow, this convention for capability PRs:

1. **Register the tool.** Add the new tool spec + handler under
   `backend/app/runtime/tools/…` and ensure it is exported so the runtime registry
   (`app/runtime/tools/__init__.py`) picks it up.
2. **Prove it exists.** Add a test that exercises the new capability end to end, so
   "the requested capability now exists" is verified, not assumed.
3. **Scope.** No unrelated refactors — keep the PR to the capability the issue
   asked for.

A capability PR that adds behavior without a test, or that doesn't register the
tool it claims to add, should be sent back for changes rather than merged.

## Operating cadence (crons, in the arq worker)

| Job | Default schedule | What it does |
|---|---|---|
| `promote_feature_backlog` | hourly at :07 | promote backlog demand ≥ `ABOS_GALAXIA_PROMOTE_MIN_VOTES` into issues (`batch` per tick) |
| `reconcile_delivered_requests` | hourly at :37 | mark promoted entries `delivered` once their issue closes; notify requesters |
| `run_business_cycle` | daily | the fleet's operating run (Galaxia included, once active) |

All are gated (`ABOS_GALAXIA_PROMOTE_ENABLED`, `ABOS_GALAXIA_RECONCILE_ENABLED`)
and no-op until Galaxia is bootstrapped and a tracker token is set.

## Kill switches, in order of bluntness

1. `DOGFOODING_AUTOMERGE=off` — stops merges, keeps issues/PRs flowing (review only).
2. `auto_merge.enabled: false` in `.github/dogfooding.yml` — same, via commit.
3. `ABOS_GALAXIA_PROMOTE_ENABLED=false` — stop turning demand into new issues.
4. `ABOS_GALAXIA_BOOTSTRAP_ENABLED=false` — don't provision/operate Galaxia at all.

## Known follow-ups

- **Revision-aware deploy verification + automated rollback.** The current health
  gate confirms the API serves after a release trigger; distinguishing the *new*
  revision and rolling back on failure needs the Render API (a per-deploy build
  marker + a rollback call). Tracked as the remainder of P1-4.
- **Deploy status → Galaxia memory.** Feeding merge/deploy outcomes back into the
  company so the fleet can observe its own shipped changes (the app-side half of
  P1-4/P1-5) is not yet wired.
