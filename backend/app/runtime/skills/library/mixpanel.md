---
name: mixpanel
title: Mixpanel
description: Instrument events or answer a product-usage question — funnels, retention, cohorts, user flows — when the behavioral data lives (or should live) in Mixpanel.
roles: product, data
---
# Mixpanel

Mixpanel is the fleet's product-analytics engine: event streams, funnels, retention, flows, and
behavioral cohorts. This skill is the ABOS-adapted path to using it well: **connect it as a tool
first, never assume it's wired**, then read real data and never invent a number.

## Connect before you query
1. **Find the tool.** `discover_tools` with query `mixpanel`; it exposes as `mcp__mixpanel__*` once it's connected (by you or the founder). Load what you need with `use_tool` (query events, funnels, cohorts).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Mixpanel in
   Settings (MCP server or service account). If the capability can't exist yet, `request_capability`.
3. **Never fabricate results.** Every metric must come from a real query — if you can't read it, say so
   and escalate. A made-up retention curve is worse than none. Event data can carry PII; run
   `check_compliance` / `list_data_policies` before exporting user-level data off-platform.

## Analyze so the answer holds up
4. **Taxonomy before instrumentation.** Define events from business questions, name them consistently
   (object-action, e.g. `Signup Completed`), and attach meaningful properties. Test in staging and keep
   a data dictionary — undocumented events cause drift that quietly poisons every downstream chart.
5. **Right report for the question.** Funnels for step-by-step drop-off, Retention for whether users
   come back, Flows for the actual paths taken. Define each funnel step as an explicit event and check
   the conversion window — a wrong window fakes a cliff that isn't there.
6. **Cohorts are behavioral, and dynamic.** Build cohorts from actions ("did X more than N times") or
   properties, and remember they update as users qualify. Segment funnels/retention by cohort to find
   *which* users convert — the aggregate hides it.
7. **Respect significance and governance.** Small samples and short windows lie; note sample size and
   don't declare a trend real on a handful of users. Enforce role-based access, minimize PII, and audit
   event volume for anomalies — governance is what keeps the numbers trustworthy.

## File the deliverable and record it
8. **File the artifact.** `save_file` the analysis / board export (category `artifact`) with the
   Mixpanel report link — the file store is the durable, shareable source.
9. **Record + hand off.** `record_metric` the real figures, `write_memory` (type `result` or
   `learning`) the insight, then `report_result` or `dispatch_task` to act on it.

## Definition of done
- Mixpanel confirmed connected (or escalated, never faked); user-data egress checked.
- Events follow a documented taxonomy; report type fits the question; findings from real queries only.
- Analysis `save_file`d with link, real metrics recorded, insight handed off.

## Common failure modes
- **Fabricated number.** Reporting a retention or funnel figure Mixpanel never returned — escalate instead.
- **Taxonomy drift.** Inconsistent event names/properties that silently corrupt every chart built on them.
- **Overreading noise.** Calling a trend on tiny samples or a mis-set conversion window.
