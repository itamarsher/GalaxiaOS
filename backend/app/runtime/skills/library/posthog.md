---
name: posthog
title: PostHog
description: Instrument product events, build funnels or retention, run feature flags/experiments, or watch session replays to understand user behavior in PostHog.
roles: product, data
---
# PostHog

PostHog is the fleet's product-analytics layer — events, funnels, retention, feature flags,
experiments, and session replay in one place. This skill is the ABOS-adapted path: **connect it as a
tool first, never assume it's wired**, then instrument a clean taxonomy so the numbers are trustworthy.

## Connect before you instrument
1. **Find the tool.** `discover_tools` with query `posthog`; it exposes as `mcp__posthog__*` once the
   founder has connected it. Load what you need with `use_tool` (query insights, list flags, read replays).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect PostHog in
   Settings (MCP server or project API key). Never invent a funnel number or a replay link — a phantom
   metric is worse than none. Run the query against the real project, or escalate.
3. **PII + egress.** Events and replays can carry personal data; `check_compliance` / `list_data_policies`
   before enabling capture on new surfaces or piping events to a destination.

## Instrument so the data is trustworthy
4. **Verb+object taxonomy, snake_case properties.** Name events like `signup_completed`,
   `report_exported`; keep properties consistent (`snake_case`, no PII in payloads). A messy taxonomy is
   the single biggest cause of untrustworthy analytics.
5. **Autocapture with a leash, mask by default.** Autocapture inflates event volume fast — use an
   allowlist and mask sensitive inputs. Define the 5-10 named events that map your core journey
   (activation → adoption → retention) explicitly.
6. **Funnels → replay → flag.** Build a funnel from signup to the first-value event; jump from a drop-off
   straight into the session replay to see *why*. Gate risky changes behind a feature flag, then attach an
   experiment measuring one primary metric plus guardrails (errors, latency).

## Record the finding
7. **Surface real numbers, then file.** `record_metric` for measurable outcomes (activation rate,
   retention); `create_report` or `save_file` (category `artifact`) the analysis with the PostHog insight
   link. `write_memory` (type `result`) the finding and `dispatch_task` any follow-up; `report_result`.

## Definition of done
- PostHog confirmed connected (or escalated, never faked); PII/egress checked before new capture.
- Named events use a consistent verb+object taxonomy; autocapture leashed and masked.
- Real metrics recorded and the analysis filed with its insight link.

## Common failure modes
- **Phantom metric.** Reporting a funnel or retention number PostHog never returned — run it or escalate.
- **Taxonomy sprawl.** Ad-hoc event names and PII in properties that rot the dataset within weeks.
- **Autocapture firehose.** Capturing everything unmasked — volume cost and a privacy exposure at once.
