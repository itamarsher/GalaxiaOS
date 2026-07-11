---
name: ahrefs
title: Ahrefs
description: Research keywords, audit backlinks, run content-gap or site-audit analysis, or track rankings in Ahrefs when SEO and competitive research run through Ahrefs.
roles: growth, research
---
# Ahrefs

Ahrefs is the fleet's SEO and competitive-intelligence engine — Keywords Explorer, Site Explorer,
Content Gap, Site Audit, and Rank Tracker. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then turn its data into a prioritized plan,
not a data dump.

## Connect before you research
1. **Find the tool.** `discover_tools` with query `ahrefs`; it exposes as `mcp__ahrefs__*` once the founder
   has connected it. Load what you need with `use_tool` (keyword volume/KD, backlinks, audit, rank data).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Ahrefs in
   Settings (MCP server or API key). Never invent a Keyword Difficulty, DR, or backlink — fabricated SEO
   data produces a plan that ranks for nothing.
3. **Spend + egress.** Ahrefs API rows are metered credits and calling it is egress; `request_budget` before
   a large pull and `check_compliance` if you export competitor/domain data.

## Turn data into a prioritized plan
4. **Keyword Difficulty in context, chase long-tail.** KD estimates ranking difficulty from the backlink
   profiles of the current top pages. For a young domain, filter to lower-KD, high-intent long-tail terms —
   a high KD without the DR to back it is a dead entry.
5. **Content Gap for the fastest wins.** Enter 2–4 competitor domains to surface keywords they rank for and
   you don't — one session yields 50–200 opportunities. This is usually the highest-leverage report; start here.
6. **Backlink audit with filters.** In Site Explorer, filter referring domains by dofollow + traffic to cut
   noise, and use Link Intersect (sites linking to competitors but not you) to build a warm outreach list —
   raw backlink counts are vanity.
7. **Site Audit + Rank Tracker on a cadence.** Run Site Audit regularly for broken links, duplicates, and
   missing meta; set Rank Tracker with grouped keywords and alerts so ranking drops surface as trends, not
   surprises. Report only Ahrefs' real figures.

## File the deliverable and record it
8. **File the plan, not the dump.** `save_file` (category `artifact`) the prioritized keyword/backlink/audit
   plan with the Ahrefs export link — a ranked shortlist, not a 500-row CSV.
9. **Record + hand off.** `write_memory` (type `result` or `learning`) the targets, `record_metric` baseline
   rankings, and `dispatch_task` content/outreach follow-up; then `report_result`.

## Definition of done
- Ahrefs confirmed connected (or escalated, never faked); credit budget and egress checked.
- KD read in context, Content Gap mined, backlinks filtered for quality, audit/rank cadence set.
- A prioritized plan filed with the export link; baselines recorded and follow-up handed off.

## Common failure modes
- **Fabricated metrics.** Inventing KD or DR when Ahrefs wasn't connected — pull real data or escalate.
- **Vanity backlinks.** Chasing referring-domain counts instead of filtered, relevant, dofollow links.
- **Data dump, no plan.** Handing over an unranked keyword export nobody can act on.
