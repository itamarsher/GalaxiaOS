---
name: semrush
title: Semrush
description: Run keyword research, position tracking, site audits, competitor analysis, or content templates in Semrush when SEO and competitive research run through Semrush.
roles: growth, research
---
# Semrush

Semrush is the fleet's SEO and competitive-research suite — Keyword Magic, Position Tracking, Site Audit,
competitor gap analysis, and the SEO Content Template. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then convert its data into a prioritized,
buildable plan.

## Connect before you research
1. **Find the tool.** `discover_tools` with query `semrush`; it exposes as `mcp__semrush__*` once the founder
   has connected it. Load what you need with `use_tool` (keyword data, tracked positions, audit, competitor pull).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Semrush in
   Settings (MCP server or API key). Never invent a volume, KD%, or Authority Score — fabricated SEO data
   yields a strategy that ranks for nothing.
3. **Spend + egress.** Semrush API units are metered and calling it is egress; `request_budget` before a
   large pull and `check_compliance` if you export competitor/domain data.

## Turn data into a prioritized plan
4. **Keyword Magic, filtered to winnable.** Start from a broad seed, then filter by intent and KD% (target
   under ~30 for a young domain) and use the auto-grouped clusters to structure content — don't ship the raw
   27-billion-keyword firehose as a plan.
5. **Competitor gap first.** Use Keyword Gap / Organic Research to find terms competitors rank for and you
   don't — that's the fastest-moving shortlist. Feed the winners into the Keyword Strategy Builder to plan pillars.
6. **Position Tracking on your real project.** Set up a tracking campaign for the actual domain and target
   keywords with alerts; report movement from tracked data, never a guess. Trend beats a one-day snapshot.
7. **Site Audit + Content Template to execute.** Run Site Audit on a cadence and fix by severity (errors
   before warnings); use the SEO Content Template to brief writers with the semantic terms, length, and
   readability real top-rankers use. Report only Semrush's real figures.

## File the deliverable and record it
8. **File the plan, not the export.** `save_file` (category `artifact`) the prioritized keyword/gap/audit
   plan plus content brief, with the Semrush project link — a ranked shortlist, not a raw dump.
9. **Record + hand off.** `write_memory` (type `result` or `learning`) the targets, `record_metric` baseline
   positions, and `dispatch_task` content/technical follow-up; then `report_result`.

## Definition of done
- Semrush confirmed connected (or escalated, never faked); API budget and egress checked.
- Keywords filtered to winnable, competitor gap mined, tracking live on the real project, audit triaged by severity.
- A prioritized plan + content brief filed with the project link; baselines recorded and follow-up handed off.

## Common failure modes
- **Fabricated metrics.** Inventing volume or KD when Semrush wasn't connected — pull real data or escalate.
- **Firehose, no filter.** Dumping thousands of keywords instead of a winnable, clustered shortlist.
- **Snapshot over trend.** Reporting a single-day ranking instead of tracked movement.
