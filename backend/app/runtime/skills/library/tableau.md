---
name: tableau
title: Tableau
description: Build or publish Tableau dashboards and data sources — extracts, calculated fields, performance tuning, or row-level security against the connected data.
roles: data
---
# Tableau

Tableau is the fleet's dashboarding and data-viz layer — published data sources and workbooks the whole
company reads from. This skill is the ABOS-adapted path to using it well: **connect it as a tool first,
never assume it's wired**, then design so dashboards load fast and each viewer sees only their rows.

## Connect before you build
1. **Find the tool.** `discover_tools` with query `tableau`; it exposes as `mcp__tableau__*` once the
   founder has connected the site. Load what you need with `use_tool` (query a data source, read a view,
   publish a workbook).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Tableau in
   Settings (MCP server or PAT). If the capability can't exist yet, `request_capability`. **Never
   fabricate a chart value or a dashboard** — pull from the real data source or escalate.
3. **Cost + egress are metered.** Extract refreshes and live queries bill the underlying warehouse;
   `request_budget` before heavy extracts or wide scans. Publishing sends data to a third party — if a
   workbook carries PII, `check_compliance` / `list_data_policies` first.

## Design for speed and per-viewer security
4. **Extracts over live, and trim them.** Unless you need real-time, use an extract — it runs in memory
   and beats live connections. Hide unused fields and minimize columns so the extract stays small; excess
   fields and worksheets are the top performance killers.
5. **Push calculations down.** Do heavy logic in the database (or the extract), not in deeply nested
   calculated fields on the view — each nested layer slows rendering. Consolidate worksheets; a dashboard
   crammed with sheets and data sources drags.
6. **Row-level security with an entitlement table.** For per-user data, join the data table to a two-
   column entitlement table (user identifier + permission key) and filter on `USERNAME()`. Keep exactly
   two tables to avoid join explosion, and resist adding descriptive columns to the security table.

## File the deliverable and record it
7. **Export and file.** Export the dashboard (PDF/image) and `save_file` (category `artifact`) with the
   Tableau URL in the description — the file store is the durable, shareable source, not memory.
8. **Record + hand off.** `write_memory` (type `result`) what shipped and the data source used;
   `record_metric` for the values reported, then `report_result` or `dispatch_task` for follow-up.

## Definition of done
- Tableau confirmed connected (or escalated, never faked); budget requested, PII egress checked.
- Extract trimmed, calculations pushed down, RLS via a two-table entitlement join where needed.
- Numbers came from the real data source; export `save_file`d and outcome recorded.

## Common failure modes
- **Fabricated values.** Inventing a chart number instead of querying the source — pull it or escalate.
- **Bloated live workbook.** Live connection with unused fields and nested calcs that takes seconds to load.
- **Broken RLS join.** A multi-table entitlement join explodes rows and leaks or duplicates data.
