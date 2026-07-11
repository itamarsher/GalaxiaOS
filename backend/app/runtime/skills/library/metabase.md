---
name: metabase
title: Metabase
description: Build dashboards, questions, or models in Metabase, set collection/data permissions, tune caching, or embed a chart for stakeholders.
roles: data
---
# Metabase

Metabase is the fleet's self-serve BI layer — questions, dashboards, and models that non-analysts can
explore. This skill is the ABOS-adapted path: **connect it as a tool first, never assume it's wired**,
then build so the numbers are real, governed, and fast.

## Connect before you build
1. **Find the tool.** `discover_tools` with query `metabase`; it exposes as `mcp__metabase__*` once the
   founder has connected it. Load what you need with `use_tool` (run a question, read a dashboard, list cards).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Metabase in
   Settings (MCP server / API key). Never invent a dashboard number or a card link — a phantom metric is
   worse than none. Run the question against the real instance, or escalate.
3. **PII + egress.** Questions read live warehouse data and embeds/downloads push it outward;
   `check_compliance` / `list_data_policies` before publishing an embed or opening download access.

## Build so it's real, governed, and fast
4. **Models as the trusted starting point.** Turn vetted queries into **models** so others build on a
   clean, documented dataset instead of re-deriving joins. Connect dashboards, models, and questions with
   links and READMEs so people find the right one.
5. **Permissions in two layers.** Set **data permissions** (which schemas/tables a group can query, who
   can run native SQL) separately from **collection permissions** (who sees which dashboards). Organize
   collections by department; mark canonical ones Official.
6. **Cache and embed deliberately.** For heavy or frequently-run dashboards set caching policies (or
   pre-run via the API) so they load in seconds instead of re-querying the warehouse each view. Prefer
   secure signed/static embeds for external sharing; full-app embedding must inherit data permissions.

## Record the finding
7. **Surface real numbers, then file.** `record_metric` for measurable outcomes; `save_file` (category
   `artifact`) or `create_report` the analysis with the Metabase link. `write_memory` (type `result`) the
   finding, `dispatch_task` any follow-up, and `report_result`.

## Definition of done
- Metabase confirmed connected (or escalated, never faked); PII/egress checked before embeds or downloads.
- Vetted queries promoted to models; data and collection permissions set per group.
- Heavy dashboards cached; external shares use secure embeds; outcome recorded with the link.

## Common failure modes
- **Phantom metric.** Reporting a number Metabase never returned — run the question or escalate instead.
- **Open permissions.** A group given native-SQL or all-collection access it shouldn't have — a data leak.
- **Uncached firehose.** A slow dashboard re-querying the warehouse on every view, racking up compute.
