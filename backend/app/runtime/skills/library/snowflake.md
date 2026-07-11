---
name: snowflake
title: Snowflake
description: Query or model data in Snowflake, size a warehouse, control credit spend, manage RBAC, or spin up a zero-copy clone for safe testing.
roles: data
---
# Snowflake

Snowflake is the fleet's cloud warehouse — compute (warehouses) and storage are billed separately by the
credit, so every query is metered spend. This skill is the ABOS-adapted path: **connect it as a tool
first, never assume it's wired**, then run lean so a stray scan doesn't burn the budget.

## Connect before you query
1. **Find the tool.** `discover_tools` with query `snowflake`; it exposes as `mcp__snowflake__*` once the
   founder has connected it. Load what you need with `use_tool` (run SQL, describe, clone).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Snowflake in
   Settings (MCP server / key-pair auth). Never fabricate a query result or a row count — a phantom number
   is worse than none. Run it against the real warehouse, or escalate.
3. **Cost is metered; PII + egress.** `request_budget` before heavy jobs (large ETL, big warehouse);
   `check_compliance` / `list_data_policies` before moving data out or granting a new role.

## Run lean and safe
4. **Right-size and auto-suspend.** Start X-Small/Small for BI, scale up only for heavy ETL — one size up
   doubles hourly credits for often no speedup. Set auto-suspend to ~60s, and use a **resource monitor**
   plus `STATEMENT_TIMEOUT_IN_SECONDS` to cap runaway spend.
5. **Optimize the query, not just the warehouse.** A bad query costs 100x more than a bad warehouse. Select
   only needed columns, filter on **clustering keys** (date columns are ideal), and lean on the 24h result
   cache for repeated dashboard queries — it returns instantly at zero compute.
6. **RBAC least privilege; clone instead of copy.** Grant via role hierarchy, never broad ACCOUNTADMIN.
   For a test/debug sandbox use **zero-copy clone** (copy-on-write, instant, near-free) rather than
   duplicating data — but drop stale clones, since diverging micro-partitions accrue storage over time.

## Record the finding
7. **Surface real numbers, then file.** `record_metric` for the measurable outcome; `create_report` or
   `save_file` (category `artifact`) the analysis/query with the result. `write_memory` (type `result`)
   the finding, `dispatch_task` any follow-up, and `report_result`.

## Definition of done
- Snowflake confirmed connected (or escalated, never faked); budget requested for heavy jobs; egress checked.
- Warehouse right-sized with auto-suspend + resource monitor; queries filter on clustering keys.
- Real results recorded and filed; sandboxes are zero-copy clones, cleaned up after.

## Common failure modes
- **Phantom result.** Reporting a row count or aggregate Snowflake never returned — run it or escalate.
- **Credit burn.** Oversized warehouse, no auto-suspend, or a full-table scan with no filter.
- **Over-privileged role.** Using ACCOUNTADMIN for routine work instead of a scoped role.
