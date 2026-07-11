---
name: meta-ads
title: Meta Ads Manager
description: Launch, structure, or optimize paid social campaigns across Facebook and Instagram in Meta Ads Manager when the fleet is spending real money to acquire customers.
roles: growth
---
# Meta Ads Manager

Meta Ads Manager is how the fleet buys reach and conversions across Facebook and Instagram. This
skill is the ABOS-adapted path to running it well: **connect it as a tool first, never assume it's
wired**, and because every impression spends real money, **meter the budget and clear the spend
before you launch.**

## Connect and clear budget before you launch
1. **Find the tool.** `discover_tools` with query `meta ads`; it exposes as `mcp__meta-ads__*` once the
   founder has connected it. Load what you need with `use_tool` (create campaign, build audience, pull stats).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Meta in
   Settings (Business Manager/API). If it can't exist yet, `request_capability`. Never invent a campaign,
   reach, or ROAS number — a phantom result is worse than none.
3. **Budget + gate first.** Ad spend is metered — `request_budget` before launching, and a large or
   ongoing spend may need `request_decision`. Ad creative is an external comm behind the approval gate;
   respect it.

## Structure so the spend converts
4. **Respect the three-level hierarchy.** Campaign (objective) > Ad Set (budget, audience, placement) >
   Ad (creative). Keep strategic and tactical decisions on their proper levels — don't fragment budget
   across too many ad sets and starve learning.
5. **Get the data layer right first.** Pixel + Conversions API firing together with deduplication is the
   baseline — Meta's AI is only as good as the events you feed it. Bad event mapping directly raises cost.
6. **Feed Advantage+ broad, differentiate on creative.** Advantage+ now activates from broad targeting +
   optimized placements + a conversion event; detailed exclusions are largely retired. Treat audience
   suggestions as hints, not walls. Creative is now the real targeting lever — test multiple hooks.
7. **Refresh creative on a clock.** Rotate creatives every ~30-45 days to beat fatigue; keep several
   variants live so the algorithm can allocate to the winner.

## Track the spend and record it
8. **Report spend and results honestly.** Pull real numbers with `use_tool`, `record_metric` for
   spend / CPA / ROAS, and `read_financials` context so spend stays inside budget.
9. **Record + hand off.** `write_memory` (type `result`/`learning`) which creative and audience won;
   `create_report` for the founder, or `report_result`.

## Definition of done
- Meta connected (or escalated, never faked); budget requested and spend metered.
- Pixel + CAPI verified; clean three-level structure; Advantage+ fed broad; creative rotating.
- Real metrics recorded; outcome reported inside budget.

## Common failure modes
- **Phantom campaign.** Claiming reach or ROAS that don't exist — escalate instead.
- **Broken signal.** Running without CAPI/pixel dedup, so the algorithm optimizes on bad data.
- **Set-and-forget budget.** Not metering or requesting budget, so spend runs past the approved cap.
