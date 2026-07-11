---
name: bigquery
title: BigQuery
description: Query, model, or schedule jobs in BigQuery — partition/cluster tables, control bytes-scanned cost, or manage dataset access.
roles: data
---
# BigQuery

BigQuery is the fleet's serverless warehouse — you're billed by **bytes scanned**, so table design and
query shape *are* the cost model. This skill is the ABOS-adapted path: **connect it as a tool first,
never assume it's wired**, then query lean so a full-table scan doesn't torch the budget.

## Connect before you query
1. **Find the tool.** `discover_tools` with query `bigquery`; it exposes as `mcp__bigquery__*` once it's connected (by you or the founder). Load what you need with `use_tool` (run SQL, dry-run, list datasets).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect BigQuery in
   Settings (MCP server / service-account key). Never fabricate a query result or row count — a phantom
   number is worse than none. Run it against the real project, or escalate.
3. **Cost is metered; PII + egress.** `request_budget` before heavy scans; `check_compliance` /
   `list_data_policies` before moving data out or granting dataset access.

## Query lean and cost-aware
4. **Dry-run before you run.** Estimate bytes with a dry run first and sanity-check against budget — never
   fire a large query blind. Select only the columns you need; on a wide table this alone can cut scan
   ~90%.
5. **Partition + cluster, then filter on them.** Partition by the primary time/range column (prune whole
   partitions), cluster on the 1-4 columns you filter within them. They only save money when your `WHERE`
   clause actually uses those columns — otherwise you scan everything anyway.
6. **Schedule idempotently, least-privilege access.** For scheduled queries use `@run_date`/`@run_time`
   and design so a re-run/backfill can't duplicate rows; run them as a minimal service account. Grant
   predefined roles (Data Viewer/Editor) at **dataset/table** level, not project-wide; use row-level
   security / column masking for sensitive data.

## Record the finding
7. **Surface real numbers, then file.** `record_metric` for the measurable outcome; `create_report` or
   `save_file` (category `artifact`) the analysis/query with the result. `write_memory` (type `result`)
   the finding, `dispatch_task` any follow-up, and `report_result`.

## Definition of done
- BigQuery confirmed connected (or escalated, never faked); budget checked for heavy scans; egress checked.
- Queries dry-run and column-scoped; tables partitioned/clustered and filters use those columns.
- Scheduled jobs idempotent under least-privilege; real results recorded and filed.

## Common failure modes
- **Phantom result.** Reporting an aggregate BigQuery never returned — run it or escalate instead.
- **`SELECT *` on a partitioned table.** No column pruning, no partition filter — a full, billed scan.
- **Backfill duplicates.** Scheduled query using `CURRENT_DATE()` instead of `@run_date`, doubling rows on re-run.
