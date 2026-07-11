---
name: optimizely
title: Optimizely
description: Design, run, or read an A/B, multivariate, or feature experiment when the test lives (or should live) in Optimizely.
roles: growth, product
---
# Optimizely

Optimizely is the fleet's experimentation platform: A/B and multivariate web tests plus feature
experimentation with server-side flags. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then let statistics — not hope — call the winner.

## Connect before you experiment
1. **Find the tool.** `discover_tools` with query `optimizely`; it exposes as `mcp__optimizely__*` once
   the founder has connected it. Load what you need with `use_tool` (experiments, variations, results).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Optimizely
   in Settings (MCP server or API token). If the capability can't exist yet, `request_capability`.
3. **Never fabricate results.** Every lift, p-value, or "winner" must come from a real results read — if
   you can't pull it, escalate rather than guess. A phantom experiment result is worse than none.
   Experiment data can carry user identifiers; `check_compliance` / `list_data_policies` before export.

## Run it so the result is trustworthy
4. **One hypothesis, defined up front.** State the primary metric, expected effect, and audience before
   launch — decide the success metric first so you can't rationalize a secondary metric into a "win."
   MVT only when you genuinely need interactions and have the traffic; otherwise A/B.
5. **Reach significance, then stop.** Optimizely's Stats Engine won't call significance until minimums
   are met (binary metrics need ~100+ visitors and 25+ conversions per arm). Run at least one full
   business cycle (7 days) to capture weekday/weekend behavior. Do not peek-and-stop the moment it goes
   green — respect the significance gate before declaring a winner.
6. **Watch for sample ratio mismatch.** If Optimizely flags an SRM (traffic split diverges from the
   intended ratio), the results are suspect — a bucketing/implementation bug, not a real effect. Stop,
   fix, and rerun; an A/A test beforehand catches config issues early.
7. **Feature experimentation ≠ deploy.** Rolling a flag to 100% is a rollout, not proof; keep the
   measured experiment separate from the release decision, and record which flag/version won.

## File the deliverable and record it
8. **File the artifact.** `save_file` the experiment readout (category `artifact`) with the Optimizely
   results link and the decision — durable and shareable, unlike agent memory.
9. **Record + hand off.** `record_metric` the real lift and significance, `write_memory` (type
   `result`/`learning`), then `report_result`; large ship/kill calls may need `request_decision`.

## Definition of done
- Optimizely confirmed connected (or escalated, never faked); experiment-data egress checked.
- Hypothesis and primary metric fixed pre-launch; ran a full cycle; winner called only on significance.
- SRM clear; readout `save_file`d with link, real metrics recorded, decision handed off.

## Common failure modes
- **Fabricated winner.** Reporting a lift Optimizely never computed — escalate instead of guessing.
- **Peeking.** Stopping the instant results turn green, shipping a false positive from an underpowered test.
- **Ignored SRM.** Trusting results despite a skewed traffic split that signals a broken implementation.
