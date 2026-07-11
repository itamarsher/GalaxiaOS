---
name: pagerduty
title: PagerDuty
description: Set up on-call schedules, escalation policies, or alert routing in PagerDuty — or respond to and tune down a noisy incident stream.
roles: platform
---
# PagerDuty

PagerDuty is the fleet's incident and on-call layer — schedules, escalation policies, alert routing, and
response. This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume
it's wired**, then route only actionable alerts, escalate by urgency, and never fabricate an incident state.

## Connect before you page anyone
1. **Find the tool.** `discover_tools` with query `pagerduty`; it exposes as `mcp__pagerduty__*` once the
   founder has connected it. Load what you need with `use_tool` (read schedules, incidents, on-call).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect PagerDuty in
   Settings (MCP server or a **scoped API token**, not an account-admin key). If the capability can't
   exist yet, `request_capability`. Never invent an incident number or claim someone was paged.
3. **Least privilege + egress.** Scope the token to the services you touch; incident payloads may carry
   customer data — `check_compliance` / `list_data_policies` before routing sensitive details through.

## Route signal, not noise
4. **Escalation by urgency, not everything at once.** Notify one target at a time; add rungs so an
   unacknowledged incident climbs to the next responder. Split **high-urgency** (pages now) from
   **low-urgency** (waits till morning) so nobody's woken for something that can wait.
5. **Filter and dedupe at the router.** Use event rules to suppress non-actionable alerts, set dedup keys,
   and normalize thresholds upstream. Correlate related alerts into one incident so a single failure isn't
   ten pages.
6. **Own the schedule.** Every service maps to a schedule with real coverage and handoffs; no gaps, no
   single hero. Test end-to-end delivery so a page actually reaches a phone.

## Respond, then file it
7. **Respond from real state.** Read the live incident before acting; acknowledge, triage, and drive it —
   confirm the underlying fix with `get_render_logs` / `get_render_deploy`, don't assume resolved.
8. **Record + hand off.** `write_memory` (type `result` / `learning`) the incident timeline and root cause;
   `record_metric` MTTR/page volume; `open_issue` the follow-up fix; `dispatch_task`, then `report_result`.
   Review page volume regularly and prune the alerts nobody acts on.

## Definition of done
- PagerDuty confirmed connected (or escalated, never faked); token scoped to the services.
- Escalation tiered by urgency; alerts filtered/deduped/correlated; schedules cover real time with no gaps.
- Incidents driven from live state; timeline, root cause, and metrics recorded and handed off.

## Common failure modes
- **Phantom incident.** Claiming someone was paged or an incident resolved when PagerDuty was never connected.
- **Alert fatigue.** Every alert high-urgency and un-deduped, so responders tune out the one that matters.
- **Schedule gaps.** A service with no on-call coverage or a broken handoff — the page reaches no one.
