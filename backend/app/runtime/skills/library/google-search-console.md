---
name: google-search-console
title: Google Search Console
description: Diagnose indexing/coverage issues, Core Web Vitals, query performance, or submit sitemaps in Google Search Console when the site's organic search health lives in GSC.
roles: growth
---
# Google Search Console

Search Console is where the fleet sees how Google actually indexes and ranks the site — coverage,
queries, Core Web Vitals, and sitemaps. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then diagnose from real Google data, not guesses.

## Connect before you diagnose
1. **Find the tool.** `discover_tools` with query `search console`; it exposes as
   `mcp__google-search-console__*` once it's connected (by you or the founder). Load what you need with `use_tool`
   (query performance, inspect a URL, submit a sitemap).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect GSC in Settings
   (MCP server or OAuth/verified property). Never invent an impression count, ranking, or "indexed" status —
   a phantom SEO metric sends the fleet chasing nothing.
3. **Least privilege + egress.** GSC exposes query and performance data; pulling it out is egress.
   `check_compliance` / `list_data_policies` if it leaves the platform.

## Diagnose from Google's own data
4. **Coverage first, by cause.** The Pages (index coverage) report is the starting point: if "discovered"
   far exceeds "indexed," read the exclusion reasons and fix by root cause (thin content, canonicals,
   noindex), not page by page.
5. **Core Web Vitals: fix Poor, mobile-first.** Optimize LCP (<2.5s), INP (<200ms), CLS (<0.1) at the 75th
   percentile. Fix "Poor" URLs before "Needs improvement," and prioritize mobile — mobile-first indexing
   means mobile scores are what rank.
6. **Query analysis for real intent.** Mine the Performance report for high-impression/low-CTR queries and
   striking-distance positions (spots 5–15) — that's where title/content tweaks convert existing visibility
   into clicks.
7. **Sitemaps + validation, then verify.** Submit the sitemap and after fixes use "Validate Fix" / URL
   Inspection to confirm Google re-crawled — don't declare a fix done until GSC confirms it. Report only what
   GSC shows; never estimate rankings.

## File the deliverable and record it
8. **File the audit.** `save_file` (category `artifact`) the coverage/CWV/query findings with the property
   and date range in the description — the file store is the durable source.
9. **Record + hand off.** `record_metric` real figures, `write_memory` (type `result`), and `dispatch_task`
   the platform agent for technical fixes (redirects, speed, markup); then `report_result`.

## Definition of done
- GSC confirmed connected (or escalated, never faked); data egress checked.
- Coverage triaged by cause, Poor CWV fixed mobile-first, striking-distance queries surfaced, fixes validated.
- Findings filed with property + date range, outcome recorded, technical follow-up handed off.

## Common failure modes
- **Phantom rankings.** Quoting positions or impressions GSC never returned — read real data or escalate.
- **Symptom whack-a-mole.** Fixing indexed pages one at a time instead of the root exclusion cause.
- **Unverified fixes.** Calling a coverage or CWV issue resolved before GSC re-crawls and confirms.
