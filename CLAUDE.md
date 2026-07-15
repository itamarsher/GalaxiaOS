# Working in this repo

## Autonomous PR pipeline

Feature PRs labeled `claude-implement` self-review and **squash-merge** via
`.github/workflows/auto-merge.yml`, gated on green CI. A PR that touches an
`escalate_paths` entry in `.github/dogfooding.yml` (auth, tenant isolation,
money, migrations, the pipeline itself) or exceeds the `escalate_diff` size
bound is routed to `founder-review` for a human instead — by design.

### Opening a PR for auto-merge

To have a PR merge itself, apply one of the `eligible_labels` from
`.github/dogfooding.yml` when you open it:

- `claude-implement` — the default for feature/bugfix PRs.
- `skill-optimize` — reserved for the skill-optimizer's playbook edits.

Steps:

1. Push the branch, then create the PR against `main`.
2. Add the `claude-implement` label (create it once with `gh label create
   claude-implement` if the repo doesn't have it yet).
3. Confirm the change is auto-merge-eligible so it doesn't silently divert to
   `founder-review`:
   - no changed file matches an `escalate_paths` glob, and
   - the diff stays within `escalate_diff` (`max_files: 15`,
     `max_total_lines: 400`).
   If either bound trips, the PR needs a human — expect `founder-review`, not a
   merge.

Once labeled, the workflow (triggered on CI success) re-verifies CI, reviews the
diff, and squash-merges + deletes the branch on a clean pass. It writes the
squash commit message itself, so no per-session trailer reaches `main`. Nothing
merges until CI is green — labeling only makes the PR *eligible*.

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
