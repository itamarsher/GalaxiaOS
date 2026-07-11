---
name: klaviyo
title: Klaviyo
description: Build or optimize e-commerce email/SMS flows, segments, and campaigns in Klaviyo when lifecycle marketing runs (or should run) through Klaviyo.
roles: growth
---
# Klaviyo

Klaviyo is where the fleet's e-commerce lifecycle marketing lives — automated flows, segments,
and campaigns tied to real store and profile data. This skill is the ABOS-adapted path to using it
well: **connect it as a tool first, never assume it's wired**, then build so revenue comes from
relevance, not blast volume.

## Connect before you send
1. **Find the tool.** `discover_tools` with query `klaviyo`; it exposes as `mcp__klaviyo__*` once it's connected (by you or the founder). Load what you need with `use_tool` (read segments, draft a flow, pull metrics).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Klaviyo in
   Settings (MCP server or private API key). Never invent a campaign, list, or open/click number — a
   phantom result is worse than none.
3. **Least privilege + egress.** Klaviyo holds customer PII (emails, phones, purchase history); syncing
   or exporting is data egress. `check_compliance` / `list_data_policies` before flowing PII out.

## Build for relevance and deliverability
4. **Flows first, campaigns second.** Automated flows drive ~41% of email revenue from ~5% of sends —
   revenue per recipient is far higher than one-off campaigns. Stand up the core set: welcome, abandoned
   cart/checkout, browse abandonment, post-purchase, and winback before scheduling broadcasts.
5. **Segment by engagement, protect the sender.** Send most often to 30/60-day engaged profiles, taper
   for the unengaged, and sunset dead addresses. This is what keeps you out of spam — deliverability is a
   segmentation problem, not a copy problem.
6. **SMS as its own channel, gated by consent.** SMS flows convert hard (top brands see double-digit
   click rates) but require explicit opt-in and quiet-hours/compliance. Trigger cart texts within hours,
   follow up ~48h later; never scrape a phone list into SMS.
7. **Ground every number in real data.** Pull opens/clicks/revenue via `mcp__klaviyo__*` or
   `read_metrics` — never estimate a benchmark as if it were this store's result.

## File the deliverable and record it
8. **Export and file.** `save_file` (category `brand` for creative, `artifact` for the flow/segment plan)
   with the Klaviyo link in the description — the file store is the durable source.
9. **Record + gate the send.** Any live send is external comms: respect the approval gate, don't route
   around it. `record_metric` real results, `write_memory` (type `result`) the outcome, `report_result`.

## Definition of done
- Klaviyo confirmed connected (or escalated, never faked); PII egress checked.
- Core flows live, segments engagement-based, SMS consent-compliant; metrics pulled from real data.
- Deliverables filed with the link, sends passed the approval gate, outcome recorded.

## Common failure modes
- **Phantom metrics.** Quoting an open rate for a campaign that never ran — read real data or escalate.
- **Blasting the whole list.** Ignoring engagement tiers, tanking deliverability for everyone.
- **SMS without consent.** Texting non-opted-in numbers — a compliance and reputation hit.
