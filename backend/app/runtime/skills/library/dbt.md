---
name: dbt
title: dbt
description: Build or change data models in dbt — staging/intermediate/marts layers, tests, sources, incremental models, documentation, or CI.
roles: data
---
# dbt

dbt is where the fleet's raw warehouse data becomes trustworthy, tested, documented models. This skill is
the ABOS-adapted path: **connect it as a tool first, never assume it's wired**, then structure the project
so lineage, tests, and CI keep the data layer honest.

## Connect before you model
1. **Find the tool.** `discover_tools` with query `dbt`; it exposes as `mcp__dbt__*` once the founder has
   connected it (dbt Cloud / MCP). Load what you need with `use_tool` (run, test, compile, list models).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect dbt in
   Settings. Never claim a model built or a test passed when it didn't — a phantom run is worse than none.
   Execute against the real project, or escalate.
3. **Cost is metered; PII + egress.** dbt runs execute on the warehouse (metered) — `request_budget`
   before large full-refresh builds; `check_compliance` / `list_data_policies` before exposing new sources.

## Structure the project so it stays honest
4. **Staging → intermediate → marts.** One staging model per source (`stg_<source>__<entity>s`), light
   renames/casts only. Business logic and joins live in intermediate; marts are wide, denormalized, and
   join-light — storage is cheap, compute is what you protect.
5. **Declare sources, materialize by cost.** Define raw tables as `sources` for lineage and freshness.
   Start models as views; promote to table when slow to query, then to **incremental** for large
   event-style data that's expensive to fully rebuild.
6. **Test and document, gated by CI.** Put a primary-key (unique + not_null) test on every re-grained
   model, plus accepted-range/relationship tests where they catch real anomalies. Document models and
   columns. Run `dbt build`/test in a sandboxed CI check on every PR — never merge red.

## Record the finding
7. **File and record.** `save_file` (category `artifact`) the run/test summary or lineage; `write_memory`
   (type `result`) what shipped and any test coverage added. `dispatch_task` downstream consumers to
   refresh, and `report_result`.

## Definition of done
- dbt confirmed connected (or escalated, never faked); budget checked for heavy builds; sources compliant.
- Layered staging/intermediate/marts naming; sources declared; materializations chosen by cost.
- Key tests + docs present; CI build/test green before merge; outcome recorded.

## Common failure modes
- **Phantom green.** Claiming models built or tests passed without a real run — execute or escalate.
- **God models.** Business logic crammed into staging, or marts with heavy joins that rebuild slowly.
- **Untested merge.** Shipping model changes with no PK test and no CI, so bad data reaches marts silently.
