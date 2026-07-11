---
name: segment
title: Segment
description: Set up event tracking through Segment — define a tracking plan, wire sources/destinations, resolve identities, or enforce data quality and PII controls.
roles: data, growth
---
# Segment

Segment (Twilio) is the fleet's customer-data pipeline — one instrumentation feeding every downstream
tool. This skill is the ABOS-adapted path: **connect it as a tool first, never assume it's wired**, then
enforce a tracking plan so clean data flows out and PII doesn't leak.

## Connect before you wire
1. **Find the tool.** `discover_tools` with query `segment`; it exposes as `mcp__segment__*` once the
   founder has connected it. Load what you need with `use_tool` (read tracking plan, list sources/destinations).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Segment in
   Settings (MCP server / workspace token). Never claim an event fired or a destination is live when it
   isn't — a phantom pipeline is worse than none. Verify against the real workspace, or escalate.
3. **Egress is the whole point — govern it.** Every destination is company data leaving to a third party;
   `check_compliance` / `list_data_policies` before connecting a new destination or turning on a matcher.

## Enforce quality and identity
4. **Tracking plan first, Object+Action naming.** Define events and properties from the key value metrics
   (signups, revenue, core usage) *before* instrumenting. Use the Object+Action convention consistently
   (`Order Completed`); never bake values into event names that belong as properties.
5. **Enforce with Protocols.** Attach the tracking plan to sources so off-spec events raise violations in
   real time — this stops bad data before it reaches destinations, instead of cleaning it up after.
6. **Identity + PII controls.** Use Unify/identity resolution to merge anonymous and known IDs into one
   profile via `identify` with a stable `userId`. Configure PII detection (default + custom regex matchers)
   in the Privacy Portal to block or hash sensitive fields before they egress to destinations.

## Record the finding
7. **File and record.** `save_file` (category `artifact`) the tracking-plan spec or destination inventory;
   `write_memory` (type `result`) what was wired and any policy applied. `record_metric` where there's a
   measurable outcome, `dispatch_task` downstream owners, and `report_result`.

## Definition of done
- Segment confirmed connected (or escalated, never faked); each destination's egress compliance-checked.
- Tracking plan defined with Object+Action naming and enforced via Protocols violations.
- Identity resolution configured; PII matchers block/hash sensitive fields; spec filed and recorded.

## Common failure modes
- **Phantom pipeline.** Claiming events flow to a destination that was never connected — verify or escalate.
- **Instrument-first, plan-never.** Events shipped with no tracking plan, so every destination inherits mess.
- **PII in the stream.** Emails or tokens flowing to destinations with no matcher — a compliance breach at scale.
