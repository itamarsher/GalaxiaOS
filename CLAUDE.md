# Working in this repo

## Autonomous PR pipeline

Feature PRs labeled `claude-implement` self-review and **squash-merge** via
`.github/workflows/auto-merge.yml`, gated on green CI. A PR that touches an
`escalate_paths` entry in `.github/dogfooding.yml` (auth, tenant isolation,
money, migrations, the pipeline itself) or exceeds the `escalate_diff` size
bound is routed to `founder-review` for a human instead — by design.

## Restart the branch from `main` after every merge

Because the pipeline **squash-merges**, a merged branch's commit lands on `main`
under a *new* SHA. If you keep building on the same branch without resetting it,
the next PR's three-dot diff (`git diff origin/main...HEAD`) re-includes those
already-merged-but-differently-SHA'd commits. When one of them touched an
`escalate_paths` file, the next PR trips a **false `founder-review` escalation**
even though your actual change is nowhere near that path. (This bit PR #161: it
re-inherited #160's `security.py` Telegram-token commit and escalated on the
auth rule.)

So after each merge, before starting the next change, restart the branch from
the freshly-updated default branch:

```sh
git fetch origin main
git checkout -B <branch-name> origin/main
```

Keep the branch name stable. If the branch still carries genuinely unmerged
commits, rebase them onto the new base (`git rebase --onto origin/main <old-base>`)
rather than discarding them — don't stack new work on already-merged history.

## Backend tests need Postgres

`backend/tests/conftest.py` skips DB-backed tests unless `ABOS_TEST_DATABASE_URL`
(an asyncpg URL) is set. The suite excludes the pgvector-backed `memory_entries`
table, so a plain Postgres without the `vector` extension is enough. Example:

```sh
export ABOS_TEST_DATABASE_URL="postgresql+asyncpg://postgres@/testdb?host=/tmp&port=5599"
```

## Deploys are manual

Render `autoDeploy` is off on `abos-api`, so a merge to `main` does **not** ship.
Trigger the deploy explicitly after a merge when a change needs to go live.
