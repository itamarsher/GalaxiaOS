---
name: datadog
title: Datadog
description: Instrument metrics, APM, or logs and set up monitors, dashboards, or SLOs in Datadog — or cut alert noise and ingestion cost.
roles: platform
---
# Datadog

Datadog is the fleet's observability plane — metrics, APM traces, logs, monitors, dashboards, and SLOs.
This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's
wired**, then alert on symptoms not noise, watch ingestion cost, and never report a status you didn't read.

## Connect before you instrument
1. **Find the tool.** `discover_tools` with query `datadog`; it exposes as `mcp__datadog__*` once the
   founder has connected it. Load what you need with `use_tool` (query metrics, list monitors, read logs).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Datadog in
   Settings (MCP server or a **scoped API + app key**, not an org-admin key). If the capability can't
   exist yet, `request_capability`. Never invent a monitor status or claim a service is healthy.
3. **Least privilege + egress.** Scope keys to what you read/write; telemetry may carry PII in logs —
   `check_compliance` / `list_data_policies`, and scrub before ingest if a policy applies.

## Alert on signal, control cost
4. **Monitor symptoms users feel.** Alert on error rate, latency, failed logins — not raw CPU. Add an
   **evaluation delay** (300s+, up to 15m for cloud metrics) and longer windows so brief spikes don't page.
5. **Every alert must be actionable.** If nobody acts on it, it's noise — delete it or downgrade to a
   dashboard. Use composite monitors to require multiple conditions, and de-flap with recovery thresholds.
6. **SLOs with burn-rate alerts.** Define an SLI, set the SLO target, and alert on **error-budget burn**
   at 10/25/50/75% — this pages before you breach, not after.
7. **Ingestion is metered spend.** Logs and custom metrics bill by volume. Filter/sample at the source,
   route only what you need, and drop chatty debug logs. `request_budget` before turning on high-volume
   ingestion (full-trace APM, debug logging) across services.

## File it and record the outcome
8. **Save dashboards + record health.** `save_file` the dashboard/monitor definition (category `artifact`)
   with the Datadog link; `record_metric` the measurable outcome (e.g. error rate, MTTR) so it's tracked.
9. **Record + hand off.** `write_memory` (type `result`) what you configured; `report_bug` / `open_issue`
   for what the telemetry surfaced; `dispatch_task` follow-up, then `report_result`.

## Definition of done
- Datadog confirmed connected (or escalated, never faked); keys scoped, PII handled.
- Monitors are symptom-based and actionable; SLOs use burn-rate alerts; ingestion cost bounded.
- Dashboards saved with links, metrics recorded, outcome handed off.

## Common failure modes
- **Phantom health status.** Claiming a service is green when Datadog was never connected — escalate instead.
- **Noise that trains people to ignore pages.** Non-actionable, flappy alerts bury the one that matters.
- **Silent ingestion blowout.** Unfiltered debug logs and custom metrics quietly run up a metered bill.
