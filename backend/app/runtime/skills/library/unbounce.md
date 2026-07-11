---
name: unbounce
title: Unbounce
description: Build, test, or optimize a standalone landing page — plus popups and sticky bars — when the conversion page lives (or should live) in Unbounce.
roles: growth
---
# Unbounce

Unbounce is the fleet's dedicated landing-page and conversion platform: drag-and-drop pages, AI Smart
Traffic routing, A/B tests, and popups/sticky bars. This skill is the ABOS-adapted path to using it
well: **connect it as a tool first, never assume it's wired**, then build one page, one goal, and let
the data pick the winner.

## Connect before you publish
1. **Find the tool.** `discover_tools` with query `unbounce`; it exposes as `mcp__unbounce__*` once the
   founder has connected it. Load what you need with `use_tool` (pages, variants, leads).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Unbounce in
   Settings (MCP server or API key). If the capability can't exist yet, `request_capability`. Never
   invent a published URL or conversion rate — a phantom page is worse than none.
3. **Egress + comms gate.** Captured leads are personal data; `check_compliance` /
   `list_data_policies` before exporting. A published page is outbound — it enters the external-comms
   log and may need founder sign-off; respect the approval gate, and `connect_domain` for a custom URL.

## Build for conversion, let data decide
4. **One page, one goal.** Match the page to the ad/message that sent the visitor, cut site navigation,
   and keep a single primary CTA above the thumb-scroll. Message match plus one goal is the core CRO
   lever — pull the brand tokens from `brand-identity-kit`.
5. **Smart Traffic vs. A/B — know the difference.** A/B test isolates **one variable** (headline, CTA,
   hero) and needs a full business cycle plus enough conversions to read. **Smart Traffic** routes each
   visitor to the variant likeliest to convert for them and starts learning from ~50 visits — use it to
   optimize across many variants, not to prove one causal change.
6. **Never call a winner early.** Wait for real significance before declaring a variant the winner and
   killing the rest — a lift on 20 conversions is noise. If unsure, keep it running or escalate.
7. **Popups + sticky bars deliberately.** Trigger on intent (exit, scroll, delay), enlarge tap targets
   to ~44px, and strip form fields to the minimum — every extra field costs conversions on mobile.

## File the deliverable and record it
8. **File the artifact.** `save_file` the page/variant spec and results (category `artifact`, or
   `brand`) with the live Unbounce link — the file store is the durable source.
9. **Record + hand off.** `record_metric` visits/conversion-rate/winner, `write_memory` (type
   `result`) what won and why, then `report_result` or `dispatch_task` to scale the winner.

## Definition of done
- Unbounce confirmed connected (or escalated, never faked); lead egress and comms gate checked.
- Page has message match + single CTA; test type fits the question; winner called only on significance.
- Page/results `save_file`d with link, metrics recorded, outcome handed off.

## Common failure modes
- **Phantom page.** Claiming a page is live when Unbounce was never connected — escalate instead.
- **Peeking to a false winner.** Declaring a variant early on too few conversions, shipping noise.
- **Multi-goal clutter.** Nav links and competing CTAs that split attention and sink the conversion rate.
