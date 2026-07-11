---
name: launchdarkly
title: LaunchDarkly
description: Ship behind a feature flag — progressive rollout, targeting rules, a kill switch, or flag cleanup — when release control lives (or should live) in LaunchDarkly.
roles: product, platform
---
# LaunchDarkly

LaunchDarkly is the fleet's feature-management platform: flags that decouple deploy from release, with
targeting rules, progressive rollouts, and instant kill switches. This skill is the ABOS-adapted path
to using it well: **connect it as a tool first, never assume it's wired**, then keep every flag small,
named, and scheduled to die.

## Connect before you flag
1. **Find the tool.** `discover_tools` with query `launchdarkly`; it exposes as `mcp__launchdarkly__*`
   once it's connected (by you or the founder). Load what you need with `use_tool` (flags, targeting, rollouts).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect
   LaunchDarkly in Settings (MCP server or API token). If the capability can't exist yet,
   `request_capability`. Never claim a flag is live or a rollout is at X% without reading it.
3. **Egress + governance.** Targeting on user attributes sends identifiers to a third party; if
   sensitive segments are involved, `check_compliance` / `list_data_policies` first.

## Flag so you don't create tech debt
4. **One flag, one decision.** Keep each flag to the smallest unit of logic — a flag that gates several
   behaviors at once is impossible to reason about. Name it so its purpose is obvious at a glance
   (`checkout-new-tax-calc`, not `flag2`) and note whether it's temporary or permanent.
5. **Roll out progressively, with a kill switch.** Ramp exposure (1% → 10% → 50% → 100%) and watch the
   metric before widening. Keep an emergency kill switch (a permanent "circuit breaker") that flips the
   feature off instantly — wire it to your APM/observability alerts where you can.
6. **Target rules narrow to broad.** Start with internal users / a beta segment, then expand. Preview
   and simulate targeting before saving so the right users get the right variation.
7. **Clean up — flags are debt.** A temporary flag past full rollout is dead conditional code. Use Code
   References to find flags with zero live references and archive them; schedule regular cleanup so debt
   doesn't compound. Removing a flag from LaunchDarkly means removing it from code too —
   `dispatch_task` the platform agent if that's separate.

## File the deliverable and record it
8. **File the artifact.** `save_file` the rollout plan / flag inventory (category `artifact`) with the
   LaunchDarkly link — the durable record of what shipped and to whom.
9. **Record + hand off.** `record_metric` rollout stage and impact, `write_memory` (type `result`)
   the flag's purpose and retirement date, then `report_result`; risky rollouts may need
   `request_decision`.

## Definition of done
- LaunchDarkly confirmed connected (or escalated, never faked); targeting-data egress checked.
- Flag is single-purpose and clearly named; rollout progressive with a working kill switch.
- Stale flags archived (or cleanup dispatched); plan `save_file`d, outcome recorded and handed off.

## Common failure modes
- **Phantom flag.** Claiming a feature is rolled out when LaunchDarkly was never connected — escalate instead.
- **Flag debt.** Leaving temporary flags in code after full rollout, littering logic no one dares delete.
- **Big-bang release.** Flipping to 100% with no ramp and no kill switch, so a bad change hits everyone at once.
