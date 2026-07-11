---
name: clay
title: Clay
description: Enrich, research, or build a prospect/account list — waterfall enrichment, Claygent research, table workflows — when the data work lives (or should live) in Clay.
roles: growth, research
---
# Clay

Clay is the fleet's data-enrichment and GTM-research platform: spreadsheet-style tables where each
column pulls live provider data, runs an AI research agent, or applies logic. This skill is the
ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, then
treat every credit as metered spend and every enriched contact as compliance-sensitive.

## Connect before you enrich
1. **Find the tool.** `discover_tools` with query `clay`; it exposes as `mcp__clay__*` once the founder
   has connected it. Load what you need with `use_tool` (tables, enrichments, exports).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Clay in
   Settings (MCP server or API key). If the capability can't exist yet, `request_capability`. Never
   invent an email, title, or company fact — a fabricated contact poisons outreach downstream.
3. **Credits are metered spend.** Enrichment burns credits (Data Credits for pulls, Actions for
   workflow ops) that cost real money and scale fast. `request_budget` before running a waterfall on a
   full list; large or irreversible runs may need `request_decision`.
4. **Enriched data is egress-sensitive.** Emails and personal attributes flowing out to providers (and
   into outreach) are screened as data egress — `check_compliance` / `list_data_policies` first, and
   remember outreach built on this data hits the external-comms gate.

## Enrich so coverage is high and clean
5. **Waterfall best provider first.** Chain 3-5 providers so each row stops at the first match —
   accuracy-first ordering keeps bad data from "winning" a row and pushes email coverage to ~85-95%.
6. **Separate finding from verifying.** Always add a verification pass; found ≠ valid. Keep bounce rate
   under ~2% or you damage sending-domain deliverability for every downstream sequence.
7. **One table, one job — and cap spend.** Build a narrow table that does one thing well before scaling.
   Set per-table credit limits, pilot on a small sample, then run the full list.
8. **Claygent for the last mile only.** The AI research agent scrapes public sources (job posts, press,
   company pages) for personalization — use it where a structured provider can't answer, not to
   re-fetch data a cheaper column already has.

## File the deliverable and record it
9. **File the artifact.** `save_file` the enriched list / research output (category `artifact`) with the
   Clay table link — the durable source. Don't route enriched contacts straight into sending around the
   comms gate.
10. **Record + hand off.** `record_metric` coverage/verified-rate/credits spent, `write_memory`
    (type `result`/`learning`), then `report_result` or `dispatch_task` the outreach step (which is gated).

## Definition of done
- Clay confirmed connected (or escalated, never faked); egress checked and budget approved before spend.
- Waterfall ordered accuracy-first with a verification pass; spend capped and piloted; bounce risk low.
- Output `save_file`d with link; coverage and credits recorded; gated outreach handed off, not bypassed.

## Common failure modes
- **Fabricated contact.** Inventing an email or fact instead of enriching — it corrupts every downstream send.
- **Credit blowout.** Running a stacked waterfall on a full list with no budget approval or per-table cap.
- **Unverified data into outreach.** Skipping the verification pass, spiking bounces and burning the domain.
