---
name: netlify
title: Netlify
description: Deploy or configure a site on Netlify — deploy previews, env vars, redirects, functions, custom domains, or a rollback.
roles: platform
---
# Netlify

Netlify hosts and deploys the fleet's front-end sites — deploy previews, build config, redirects,
serverless functions, and instant rollbacks. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then keep secrets out of the repo and verify the
deploy is actually live.

## Connect before you deploy
1. **Find the tool.** `discover_tools` with query `netlify`; it exposes as `mcp__netlify__*` once it's connected (by you or the founder). Load what you need with `use_tool` (trigger deploys, read status, manage env).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Netlify in
   Settings (MCP server or a **scoped personal-access token**, not an account-owner token). If the
   capability can't exist yet, `request_capability`. Never invent a deploy URL or claim a site is live.
3. **Least privilege + egress.** Scope the token to the site; the build ships source to a third party —
   `check_compliance` / `list_data_policies` if anything sensitive is in the repo or env.

## Ship and configure it well
4. **Preview every change, don't push to prod.** Deploy Previews build from each PR (`deploy-preview-N--
   site.netlify.app`) so a human/agent reviews the real thing before it goes live. Add custom headers to
   keep branch deploys out of search indexes.
5. **Secrets in Netlify env, never in the repo.** Set env vars via the UI/CLI/API, scoped by context
   (production vs deploy-preview) — sensitive values must not live in `netlify.toml` or source. Functions
   read secrets from `env` at runtime.
6. **Redirects and functions in config.** Put redirects/rewrites and function settings in `netlify.toml`
   (or `_redirects`) so they're versioned and reviewable, not clicked in the UI. Serverless/edge functions
   handle dynamic bits; keep static assets on the CDN.

## Verify, then file it
7. **Verify the live deploy, not the build log.** A successful build is not a live site — hit the published
   URL and confirm with `get_render_deploy` / `get_render_logs` (or Netlify's deploy status) before
   reporting success. Rollback is instant: publish a previous atomic deploy if the new one regresses.
8. **Record + hand off.** `write_memory` (type `result`) the deploy URL and what shipped; `report_bug` /
   `open_issue` for build failures; `dispatch_task` follow-up, then `report_result`.

## Definition of done
- Netlify confirmed connected (or escalated, never faked); token site-scoped.
- Change previewed before prod; secrets in scoped env vars; redirects/functions in versioned config.
- Live deploy verified end-to-end (rollback path known); URL and outcome recorded and handed off.

## Common failure modes
- **Phantom deploy.** Claiming a site is live when Netlify was never connected — escalate instead.
- **Secrets in the repo.** API keys in `netlify.toml` or source instead of scoped env vars.
- **Green-build trust.** Reporting success off a passed build without loading the published URL.
