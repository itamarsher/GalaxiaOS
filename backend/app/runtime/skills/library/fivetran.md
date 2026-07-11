---
name: fivetran
title: Fivetran
description: Set up or manage a Fivetran managed connector to sync a source into the warehouse — sync frequency, schema drift, or controlling MAR-based cost.
roles: data
---
# Fivetran

Fivetran is the fleet's managed ELT — connectors that extract from sources and load them into the
warehouse, adapting to schema changes on their own. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then run it so you don't pay for rows nobody uses.

## Connect before you sync
1. **Find the tool.** `discover_tools` with query `fivetran`; it exposes as `mcp__fivetran__*` once the
   founder has connected the account. Load what you need with `use_tool` (list connectors, trigger a
   sync, read status).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Fivetran in
   Settings (MCP server or API key). If the capability can't exist yet, `request_capability`. **Never
   fabricate a synced table or row count** — check the real connector or escalate.
3. **Cost + egress are metered.** Fivetran bills by Monthly Active Rows (MAR — distinct primary keys
   modified per month), so a new connector is real recurring spend; `request_budget` before adding one.
   A connector pulls source data into your warehouse — if it carries PII, `check_compliance` /
   `list_data_policies` first.

## Run connectors so cost stays proportional to value
4. **Sync only what's used.** MAR is driven by how many unique rows change, not how often you sync — so
   block schemas and tables you don't need rather than syncing everything. Frequency doesn't change MAR;
   scope does.
5. **Match frequency to how fresh the data must be.** Reserve minute/quarter-hour syncs for data that's
   actually consumed that fresh; slow down low-value connectors. This is the most direct MAR lever after
   scoping.
6. **Own schema drift downstream.** Fivetran auto-adapts when a source adds a column or changes a type —
   convenient, but unmonitored drift silently breaks downstream dbt models and dashboards. Watch for new
   columns and reconcile the transform layer; audit connectors quarterly for high-MAR/low-value sources.

## File the deliverable and record it
7. **Document the pipeline.** `save_file` (category `artifact`) the connector config, synced schema, and
   destination with the Fivetran link — the file store is the durable source, not memory.
8. **Record + hand off.** `write_memory` (type `result`) the connector and its MAR footprint;
   `record_metric` for rows synced, then `dispatch_task` the data agent to build transforms, or
   `report_result`.

## Definition of done
- Fivetran confirmed connected (or escalated, never faked); budget requested, PII egress checked.
- Only needed schemas/tables synced; frequency matched to freshness need; drift monitoring in place.
- Real connector status confirmed; config `save_file`d and MAR/outcome recorded.

## Common failure modes
- **Sync-everything MAR bloat.** Loading unused tables inflates MAR and the bill for data nobody queries.
- **Silent schema drift.** An auto-added column that quietly breaks the downstream model until someone notices.
- **Phantom sync.** Claiming a table landed when Fivetran was never connected — verify or escalate.
