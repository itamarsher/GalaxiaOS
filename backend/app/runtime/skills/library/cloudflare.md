---
name: cloudflare
title: Cloudflare
description: Manage DNS, CDN caching, WAF/security, SSL/TLS modes, page rules, or Workers for a domain in Cloudflare.
roles: platform
---
# Cloudflare

Cloudflare fronts the fleet's domains — DNS, CDN caching, WAF, SSL/TLS, page rules, and Workers. This
skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**,
then use scoped tokens, encrypt end-to-end, and verify changes actually took at the edge.

## Connect before you change DNS — two surfaces, pick by the job
Cloudflare reaches the fleet two independent ways. Onboard the one your task needs — both are
self-serve, neither needs the founder.
1. **Generic Cloudflare ops (DNS records, cache purge, WAF, Workers).** `discover_tools` query
   `cloudflare`; it exposes as `mcp__cloudflare__*` once connected (by you or the founder). Not there?
   Onboard it yourself: sign up, self-issue a **scoped API token** (never the Global API Key), then
   register Cloudflare's MCP endpoint with `connect_service`. Load what you need with `use_tool`.
2. **ABOS-native hosting (`publish_content`, `connect_domain` — site publish, custom domain, HTTPS).**
   These are powered by ABOS's built-in Cloudflare adapter, NOT the MCP server, so connecting an MCP
   server does *not* enable them. Turn them on yourself with `configure_integration` (provider
   `cloudflare`, a scoped `api_token` + your `account_id`) — ABOS verifies and stores it — then `use_tool`
   the native tools and use them directly.
3. **Can't get a credential? Escalate — don't fake it.** Only if a credential genuinely needs the founder
   (their identity, payment, or a login only they have), `request_user_action` for them to add Cloudflare
   in Settings. If the capability can't exist yet, `request_capability`. Never invent a DNS record or claim
   a domain is live.
4. **Least privilege + one token per job.** Scope each token to a single zone and the exact permission
   (e.g. edit DNS *only*) — so a leaked or rotated token can't touch other services. DNS changes are egress-
   relevant; `check_compliance` if a record exposes internal infrastructure.

## Configure the edge correctly
5. **Proxy the right records, DNS-only the rest.** Orange-cloud the site/API/asset hosts for CDN + WAF;
   keep mail (MX), and third-party verification records **DNS-only** so you don't break delivery or checks.
   Enable DNSSEC if the registrar supports it.
6. **SSL/TLS Full (Strict), never Flexible.** Full (Strict) with a valid origin cert gives end-to-end
   encryption; Flexible causes mixed-content and redirect loops. Set minimum TLS 1.2, prefer 1.3.
7. **WAF in simulate, then block.** Turn on managed rules in *simulate*, review logs a couple of days, then
   promote high-confidence rules to *block*. Cache static assets aggressively; keep dynamic/auth paths
   uncached. Workers secrets go in `wrangler secret put` — never in config or source.

## Verify, then file it
8. **Verify at the edge, not off the dashboard.** DNS/cache/SSL changes propagate — confirm with a real
   `dig`/`curl` against the hostname (and `get_render_logs` for origin) before reporting success.
9. **Record + hand off.** `write_memory` (type `result`) the records/rules changed; `report_bug` /
   `open_issue` for anything the WAF or origin surfaced; `dispatch_task` follow-up, then `report_result`.

## Definition of done
- Cloudflare confirmed connected (or escalated, never faked); token single-zone, single-permission.
- Correct records proxied vs DNS-only; SSL Full (Strict) + TLS 1.2/1.3; WAF tuned; secrets in Wrangler.
- Change verified live at the edge; records/rules recorded and handed off.

## Common failure modes
- **Phantom domain.** Claiming a site is live or a record set when Cloudflare was never connected — escalate.
- **Flexible SSL.** Half-encrypted traffic and redirect loops from the wrong SSL mode.
- **Global-key sprawl.** One all-powerful key everywhere, so any leak compromises every zone at once.
