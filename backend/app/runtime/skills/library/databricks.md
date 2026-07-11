---
name: databricks
title: Databricks
description: Run notebooks, jobs, or Delta/lakehouse work in Databricks — cluster and DBU cost control, Unity Catalog governance, or querying real warehouse data.
roles: data
---
# Databricks

Databricks is the fleet's lakehouse — notebooks, jobs, and Delta tables governed by Unity Catalog over
warehouse-scale compute. This skill is the ABOS-adapted path to using it well: **connect it as a tool
first, never assume it's wired**, then run it so clusters don't burn DBUs and governance stays central.

## Connect before you compute
1. **Find the tool.** `discover_tools` with query `databricks`; it exposes as `mcp__databricks__*` once
   the founder has connected the workspace. Load what you need with `use_tool` (run a query, submit a
   job, read a table).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Databricks
   in Settings (MCP server or PAT). If the capability can't exist yet, `request_capability`. **Never
   fabricate a query result or row count** — run it on the real cluster or escalate.
3. **Cost + egress are metered.** Compute bills in DBUs and a big cluster is real spend;
   `request_budget` before heavy jobs or large clusters. Reading governed data is screened as egress —
   if a table holds PII, `check_compliance` / `list_data_policies` first.

## Govern with Unity Catalog, control DBUs
4. **Managed tables in Unity Catalog.** Prefer managed Delta tables so Unity Catalog owns both governance
   and data files — that's what gives you lineage, access control, and optimization. Define principals at
   the account level and grant via groups, not individuals.
5. **Right-size and auto-terminate compute.** Match the cluster to the workload, enable auto-termination
   and autoscaling, and use spot instances for non-critical jobs — an idle cluster bills DBUs for nothing.
   Turn ad-hoc work into scheduled jobs rather than leaving interactive clusters running.
6. **Optimize Delta, don't over-partition.** Use Liquid Clustering (or `OPTIMIZE`) instead of rigid
   partitioning on large evolving tables — it speeds queries and cuts the compute each one costs. Tag
   clusters by team/project so spend is attributable and reviewable.

## File the deliverable and record it
7. **Export and file.** Export the notebook/result and `save_file` (category `artifact`) with the
   workspace/job link in the description — the file store is the durable, shareable source, not memory.
8. **Record + hand off.** `write_memory` (type `result`) the job and table touched; `record_metric` for
   the values reported and DBUs consumed, then `report_result` or `dispatch_task` for follow-up.

## Definition of done
- Databricks confirmed connected (or escalated, never faked); budget requested, PII egress checked.
- Managed tables under Unity Catalog; clusters right-sized with auto-termination; Delta optimized.
- Results came from the real cluster; export `save_file`d and outcome/DBUs recorded.

## Common failure modes
- **Idle cluster burn.** Leaving an interactive cluster running with no auto-termination bleeds DBUs.
- **Governance bypass.** External tables or per-user grants outside Unity Catalog break lineage and control.
- **Fabricated result.** Reporting a number without running the query — run it on the cluster or escalate.
