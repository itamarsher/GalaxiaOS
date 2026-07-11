---
name: github
title: GitHub
description: Work in a GitHub repo — review a PR, set branch protection, wire up Actions/CI, cut a release, or manage issues when the code lives on GitHub.
roles: platform, product
---
# GitHub

GitHub is where the fleet's code, review, and CI live. This skill is the ABOS-adapted path to using it well: **connect it as a tool first with least-privilege credentials, never assume it's wired**, then verify changes land end-to-end rather than trusting a green check at a glance.

## Connect before you touch the repo
1. **Find the tool.** `discover_tools` with query `github`; GitHub exposes as `mcp__github__*` once connected. Prefer the natural ABOS tools where they fit — `list_repo_files`, `read_repo_file`, `open_issue` — and `use_tool` for PRs, reviews, and Actions.
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect GitHub in Settings with a **fine-grained token scoped to the specific repo and the minimum scopes** (read unless you must write). If the capability can't exist yet, `request_capability`. Never invent a PR number, commit SHA, or claim CI passed — a phantom status is worse than none.
3. **Least privilege + egress.** Repo access sends code to a third party; if the repo carries anything sensitive, `check_compliance` / `list_data_policies` first.

## Work the repo safely
4. **Protect the default branch.** Require PRs (no direct pushes to main), passing checks, and review before merge — this gates workflow-file edits too. Never merge your own unreviewed change into a protected branch.
5. **Review substantively, not rubber-stamp.** Read the diff for correctness and security, leave line-specific comments, and confirm the change matches the issue it closes. A green check is necessary, not sufficient.
6. **Harden Actions.** Grant `GITHUB_TOKEN` the minimum `permissions:` per job (default read-only), pin third-party actions to a full commit SHA, and prefer OIDC short-lived tokens over long-lived secrets. Read `get_job_logs` on failure instead of guessing.
7. **Release cleanly.** Tag from a merged, CI-green commit; write release notes from the merged PRs; don't tag off a dirty or unverified branch.

## Verify, file, and record
8. **Confirm end-to-end.** After a merge or deploy-triggering push, verify the run actually succeeded (`get_render_deploy` / `get_render_logs` where ABOS deploys) — don't report success off the merge alone.
9. **Record and hand off.** `write_memory` (type `result`) the PR/release URL; `report_bug` / `open_issue` for follow-ups; `dispatch_task` or `report_result`.

## Definition of done
- GitHub connected with a least-privilege, repo-scoped token (or escalated, never faked); egress checked.
- Branch protected; PR reviewed substantively; Actions least-privileged and SHA-pinned.
- Change verified to actually pass/deploy; PR/release link recorded and handed off.

## Common failure modes
- **Phantom status.** Claiming a PR merged or CI passed when it wasn't verified — check the real run.
- **Over-scoped token.** A broad or org-wide PAT where a fine-grained repo-scoped one would do.
- **Rubber-stamp review.** Approving on a green check without reading the diff for correctness or secrets.
