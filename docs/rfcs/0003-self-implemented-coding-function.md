# RFC 0003 — A self-implemented coding function: bundle-backed repos, no git server

- **Status:** Draft. Slice 1 (the self-owned repo store + MCP surface) lands with this RFC.
- **Scope:** How a coding/engineering function keeps durable code state and returns
  reviewable changes **without a git server and without GitHub** — honoring the
  in-house-first tenet (RFC 0002). Builds on RFC 0001 (functions as worker slots).

## The gap

RFC 0001's `ConnectedBackend` lets any external agent runtime (OpenClaw, opencode,
Claude Code) staff a function slot. But a *coding* function needs three things the
generic surface doesn't give it: durable repo state that survives the ephemeral
worker, a starting point handed to the worker, and a way to get the change back for
review. The obvious answers pull in exactly what the tenet forbids — a hosted git
server (a heavyweight, stateful, multi-tenant subsystem every self-hoster would run)
or GitHub (an external account + API).

## The design: the repo *is* a `git bundle` on the company file store

`git bundle` serializes an entire repo — full history, all refs — into **one file
that is itself a valid git remote** (you can `git clone`/`fetch`/`pull` from it).
That is the unlock:

- **Durable state** = a bundle stored via the existing `FileProvider` seam
  (`services/files.py`) under a new `code` category, keyed by repo name. No server,
  no new signup — it rides the one storage provider the founder already connects at
  launch, and tenant isolation comes free from the file store. Galaxia treats
  bundles as **opaque bytes** (no git runs on Galaxia's side).
- **Execution** stays in the worker's ephemeral sandbox (opencode's working dir).
  Per initiative: fetch the bundle → `git clone` it locally → edit + run tests →
  `git commit` on a branch → `git bundle create` → push the new bundle back, with a
  `git diff` as the reviewable artifact.
- **Review / "merge" = a Galaxia governance decision**, not a GitHub PR. The worker
  proposes the diff via the existing `request_decision`; on approval it pushes the
  new bundle as canonical. This reuses the decision inbox + artifact index Galaxia
  already owns — more on-brand than an external PR, and self-implemented end to end.
- **Concurrency**: initiatives are already serialized per function (one coding
  initiative at a time), and git is the merge engine *inside* the sandbox — the
  store only ever holds a linearized, already-merged bundle. A version tag + lease
  in the manifest is reserved for future multi-writer repos.

Why not host a git server: it buys almost nothing over bundles for an autonomous
coding function producing reviewed diffs, and costs a whole stateful multi-tenant
service. A hosted remote only earns its place with many concurrent live workers on
one repo, external human developers using normal git tooling, or repos too large to
re-bundle per initiative — none of which apply to v1.

## The worker binding: opencode as a pull/connected agent

opencode connects **out** to Galaxia's Business-Function MCP (`bf_mcp`) with a
per-`(company, function)` token — so there is **zero opencode-specific code** on
Galaxia's side; opencode is just an MCP client calling our tools. It pulls its
mandate + initiative, calls `get_repo` for the bundle, does the work in its own
sandbox, and calls `push_repo` (after a `request_decision` review when governance
requires it). The same surface works for any MCP-capable coding runtime.

A ready template ships in `gateway/config/opencode.json` (registers the MCP
endpoint as a remote server; secrets via `{env:…}`) + `opencode-galaxia-coding.md`
(the coding loop). See `gateway/README.md` → *Connect opencode as a coding
function* for the mint-token → connect flow.

## What lands in slice 1 (this PR)

- **`services/repo.py`** — the bundle repo store over `FileProvider`: `save_bundle`
  / `load_bundle` / `list_repos`, base64 transport helpers, and a size guard
  (`repo_max_bundle_bytes`). Migration-free: `code` is a new `FileCategory` (a
  non-native varchar enum) and bundles reuse the `CompanyFile` manifest.
- **`bf_mcp` repo tools** — `get_repo`, `push_repo`, `list_repos`, tenant-scoped by
  the connection token exactly like the file tools; `code` is excluded from the
  text `save_file`/`list` tools (bundles are binary).
- **The `engineering` catalog block** (RFC 0002) — a selectable, in-house function
  staffed by `custom`, with health signals (`code_tasks_shipped`, `ci_pass_rate`,
  `review_turnaround_hours`). It provisions through the function-first path and
  binds to the connected runtime when one is configured (`worker_binding`).

## Follow-ups

- The review→promote flow as a first-class merge decision (v1 composes
  `request_decision` + `push_repo`; a dedicated coding-review decision kind is next).
- Multi-writer repos: the manifest version + lease (initiative serialization covers
  v1).
- Auto-capture of `code_tasks_shipped` / `ci_pass_rate` from initiative outcomes
  (RFC 0002 `signal_capture` sources).
- A first-party object store behind `FileProvider` for deployments that want zero
  external storage dependency — the bundle design doesn't change.
