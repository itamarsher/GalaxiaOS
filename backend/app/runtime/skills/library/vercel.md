---
name: vercel
title: Vercel
description: Ship or operate a frontend on Vercel — check a preview deploy, set env vars, promote to production, roll back a bad release, or wire a custom domain.
roles: platform
---
# Vercel

Vercel is where the fleet's frontends deploy — preview builds per branch, production, and the domains in front of them. This skill is the ABOS-adapted path to using it well: **connect it as a tool first with least-privilege credentials, never assume it's wired**, then verify what actually went live instead of trusting that a push shipped.

## Connect before you deploy
1. **Find the tool.** `discover_tools` with query `vercel`; Vercel exposes as `mcp__vercel__*` once connected. Load what you need with `use_tool` (read a deployment, list env vars, promote or roll back).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Vercel in Settings with a **token scoped to the specific project**, minimum access. If the capability can't exist yet, `request_capability`. Never invent a deployment URL or claim a build is live — a phantom deploy is worse than none.
3. **Least privilege + egress.** Deploy data and env vars are sensitive; screen with `check_compliance` / `list_data_policies` before exporting secrets or logs off-platform.

## Ship and operate safely
4. **Verify on the preview before production.** Every non-production branch/PR gets a preview URL — test there first. If a preview exposes sensitive data, enable deployment protection; previews are public by default.
5. **Scope env vars per environment.** Set values separately for Production / Preview / Development; never commit `.env` or reuse prod secrets in preview. Keep edge-runtime vars small (per-var size limits apply).
6. **Recover with Instant Rollback, don't hot-fix under fire.** A bad release reverts instantly by re-pointing domains to a known-good prior deployment — reach for that first, then fix forward calmly. Where available, roll a release out to a fraction of traffic and watch metrics before full promotion.
7. **Wire domains the reliable way.** Use CNAME (not hard-coded A records), make `www` primary with the apex redirecting to it, and confirm the domain verifies. Turn on Web Analytics / Speed Insights and spend alerts.

## Verify, file, and record
8. **Confirm what's live.** Read the actual deployment state (`get_render_deploy` / `get_render_logs` where ABOS mirrors it) and confirm the intended commit is serving production — don't report success off the push.
9. **Record and hand off.** `write_memory` (type `result`) the production URL and deploy ID; `report_bug` for a failed build; `dispatch_task` or `report_result`.

## Definition of done
- Vercel connected with a least-privilege, project-scoped token (or escalated, never faked); secret egress checked.
- Change verified on preview; env vars scoped per environment; domain on CNAME with www primary.
- Live deployment verified against the intended commit; URL/deploy ID recorded and handed off.

## Common failure modes
- **Phantom deploy.** Claiming a build is live without reading the real deployment state — verify it.
- **Leaked or crossed env vars.** Committing `.env` or reusing production secrets in preview.
- **Panic hot-fix.** Debugging a broken production instead of an Instant Rollback to the last good deploy.
