---
name: circleci
title: CircleCI
description: Author or debug a CircleCI pipeline — config.yml, orbs, caching, parallelism, or contexts and required checks for a repo.
roles: platform
---
# CircleCI

CircleCI runs the fleet's build/test/deploy pipeline off `.circleci/config.yml`. This skill is the
ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, then write
config that's fast, reproducible, and can't leak production secrets — and verify the deploy really landed.

## Connect before you build
1. **Find the tool.** `discover_tools` with query `circleci`; it exposes as `mcp__circleci__*` once it's connected (by you or the founder). Load what you need with `use_tool` (read pipeline status, trigger, get logs).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect CircleCI in
   Settings (MCP server or a **project-scoped API token**, never a personal/org-admin token). If the
   capability can't exist yet, `request_capability`. Never invent a pipeline URL or claim a build is green.
3. **Least privilege + egress.** Scope tokens to the project; builds ship source and logs to a third party —
   `check_compliance` / `list_data_policies` if anything sensitive flows through.

## Write config that's fast and safe
4. **Pin orbs to an exact version.** Orbs are remote code that runs in your pipeline — `circleci/node@5.2.0`,
   never a floating major. An unpinned ref can silently change behavior; upgrades should be a reviewed commit.
5. **Cache on the lockfile checksum.** Key caches with `{{ checksum "package-lock.json" }}` and a partial
   fallback key — you get warm rebuilds without ever restoring stale dependencies.
6. **Parallelism needs splitting.** Setting `parallelism: N` alone runs the full suite N times. Pipe tests
   through `circleci tests split` (using timing data) so each container runs a real subset and you gain speed.
7. **Secrets live in Contexts, not vars.** Put production credentials in a **context** restricted to a
   security group and gated to protected branches — never in `config.yml` or an all-branches project var.
   Make the build/test job a required check on the default branch.

## Verify, then file it
8. **Verify end-to-end, not off green.** A passed workflow is not a shipped release — confirm with
   `get_render_deploy` / `get_render_logs` (or the live URL) before reporting success.
9. **Record + hand off.** `write_memory` (type `result`) the pipeline link and outcome; `report_bug` /
   `open_issue` for failures worth fixing; `dispatch_task` follow-up, then `report_result`.

## Definition of done
- CircleCI confirmed connected (or escalated, never faked); token project-scoped.
- Orbs pinned, caches keyed on lockfile, parallelism split, secrets in a gated context.
- Deploy verified live end-to-end; pipeline link and outcome recorded and handed off.

## Common failure modes
- **Phantom green build.** Claiming a workflow passed when CircleCI was never connected — escalate instead.
- **Floating orb.** An unpinned orb pulls a new release that breaks the build with no commit of yours.
- **Parallelism without splitting.** N containers each run the whole suite — cost N×, zero speedup.
