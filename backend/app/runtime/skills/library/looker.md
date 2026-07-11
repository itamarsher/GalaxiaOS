---
name: looker
title: Looker
description: Model data in LookML, build governed explores and dashboards, or manage PDTs and permissions in Looker against the connected warehouse.
roles: data
---
# Looker

Looker is the fleet's governed BI layer — LookML models over the warehouse that turn raw tables into
trusted explores and dashboards. This skill is the ABOS-adapted path to using it well: **connect it as a
tool first, never assume it's wired**, then model so metrics are defined once and queries stay cheap.

## Connect before you model
1. **Find the tool.** `discover_tools` with query `looker`; it exposes as `mcp__looker__*` once the
   founder has connected the instance. Load what you need with `use_tool` (run a look, read LookML,
   query an explore).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Looker in
   Settings (MCP server or API credentials). If the capability can't exist yet, `request_capability`.
   **Never fabricate a number, look, or dashboard** — run it against the real explore or escalate.
3. **Cost + egress are metered.** Every explore query bills warehouse compute; `request_budget` before
   heavy PDT builds or wide scans. Data leaving Looker is screened as egress — if a model exposes PII,
   `check_compliance` / `list_data_policies` first.

## Model so metrics are defined once
4. **Define every measure in LookML, once.** Put business logic (revenue, active user) in the model, not
   in each dashboard — governed explores exist so numbers don't diverge tile to tile. Give every view a
   primary key so symmetric aggregation is correct across joins.
5. **PDTs for heavy work, datagroups for freshness.** Use persistent derived tables for expensive joins
   and large aggregations, not small simple sets. Trigger rebuilds with `datagroup_trigger` tied to
   source freshness rather than a blind `persist_for` timer — that's what keeps compute and staleness low.
6. **Everything through Git.** LookML changes go through the project's Git branch and review — never edit
   production in place. One project maps to one repo; validate before deploy so a broken model doesn't
   take down shared explores.

## File the deliverable and record it
7. **Export and file.** Export the dashboard/look (PDF/CSV) and `save_file` (category `artifact`) with
   the Looker URL in the description — the file store is the durable, shareable source, not memory.
8. **Record + hand off.** `write_memory` (type `result`) the metric and its LookML definition;
   `record_metric` for the values reported, then `report_result` or `dispatch_task` for follow-up.

## Definition of done
- Looker confirmed connected (or escalated, never faked); budget requested, PII egress checked.
- Measures defined once in LookML; PDTs use datagroup triggers; changes went through Git.
- Numbers came from the real explore; export `save_file`d and outcome recorded.

## Common failure modes
- **Fabricated numbers.** Inventing a metric instead of querying the explore — run it or escalate.
- **Logic in dashboards, not the model.** Per-tile calculations drift, so the same metric disagrees.
- **PDT sprawl.** Persisting small sets or timer-rebuilding heavy ones burns warehouse compute for nothing.
