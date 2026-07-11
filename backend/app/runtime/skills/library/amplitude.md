---
name: amplitude
title: Amplitude
description: Design an event taxonomy, build cohorts/funnels, track the North Star, or audit data quality and governance in Amplitude.
roles: product, data
---
# Amplitude

Amplitude is the fleet's behavioral-analytics system of record — one governed taxonomy powering funnels,
cohorts, journeys, and experiments. This skill is the ABOS-adapted path: **connect it as a tool first,
never assume it's wired**, then design a taxonomy disciplined enough to trust downstream.

## Connect before you analyze
1. **Find the tool.** `discover_tools` with query `amplitude`; it exposes as `mcp__amplitude__*` once the
   founder has connected it. Load what you need with `use_tool` (query charts, list events, read cohorts).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Amplitude in
   Settings (MCP server or API key). Never invent a chart number or a cohort size — a phantom metric is
   worse than none. Query the real project, or escalate.
3. **PII + egress.** Event properties and user identifiers can carry personal data; `check_compliance` /
   `list_data_policies` before instrumenting new surfaces or syncing a cohort to a destination.

## Design a governed taxonomy
4. **Noun+verb, outcome-driven.** Name events predictably — `Checkout Completed`, `Report Exported`, not
   `export_report`. Track outcomes that map to business goals, not every click. Consistency is what lets a
   single taxonomy power funnels, cohorts, and experiments without translation.
5. **Govern it — owner, approval, versioning.** Designate one taxonomy owner; new events go through a
   request/approval flow before shipping. This is the difference between a clean dataset and chaos.
6. **Define the North Star, build cohorts off it.** Pick one North Star metric and instrument the events
   feeding it; build cohorts (e.g. activated-last-week) and funnels around real conversion moments. Audit
   regularly for volume anomalies that signal a broken implementation.

## Record the finding
7. **Surface real numbers, then file.** `record_metric` for measurable outcomes (North Star, activation,
   retention); `create_report` or `save_file` (category `artifact`) the analysis with the Amplitude chart
   link. `write_memory` (type `result`) the finding, `dispatch_task` follow-up, and `report_result`.

## Definition of done
- Amplitude confirmed connected (or escalated, never faked); PII/egress checked before new instrumentation.
- Events follow a governed noun+verb taxonomy with a named owner and approval flow.
- Real metrics recorded and the analysis filed with its chart link.

## Common failure modes
- **Phantom metric.** Reporting a number Amplitude never returned — query it or escalate instead.
- **Ungoverned sprawl.** Anyone adding events freely, so the taxonomy fragments and analysis breaks.
- **Vanity North Star.** Optimizing an event with no line to real business value.
