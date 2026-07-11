---
name: tiktok-ads
title: TikTok Ads
description: Launch, scale, or refresh paid acquisition on TikTok — Spark Ads, Smart+ campaigns, or diagnosing creative fatigue on a running ad set.
roles: growth
---
# TikTok Ads

TikTok is a creative-led performance channel: the algorithm finds buyers from the video, not from
tight demographic filters. This skill is the ABOS-adapted path to spending there well — **connect it
as a tool first, never assume it's wired**, then treat every launch as metered spend that clears the
budget and external-comms gates before a dollar moves.

## Connect before you spend
1. **Find the tool.** `discover_tools` with query `tiktok`; TikTok Ads exposes as `mcp__tiktok-ads__*`
   once the founder has connected the ad account. Load what you need with `use_tool`.
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect TikTok Ads
   Manager (MCP server or access token). Never invent a campaign ID, spend figure, or a live ad — a
   phantom campaign is worse than none.
3. **Clear the money and comms gates.** Ad spend is metered: `request_budget` before launch and
   `request_decision` for large or open-ended budgets. Ads are outbound external comms — they're
   indexed and may need founder sign-off. Don't route around the approval gate.

## Spend the way the platform rewards
4. **Lead with Spark Ads.** Boost native organic-style posts (yours or a creator's) rather than
   polished commercials — they carry real engagement signals and outperform in-feed ads. Aim to run
   the majority of budget through Spark. Hook in the first 3 seconds or the view is lost.
5. **Go broad, let Smart+ optimize.** Use Smart+ (Smart Performance) campaigns and broad targeting;
   layering too many interest filters starves the algorithm of signal and slows learning. Feed it
   3-5 creatives per ad group across 3-5 ad groups, and a clean pixel/Events API conversion signal.
6. **Fight creative fatigue on a clock.** TikTok fatigues faster than other channels: refresh hooks
   every few days and whole videos every 7-10 days. `read_metrics` on CTR/CPA — when frequency climbs
   and CTR decays, rotate new variations before efficiency collapses. `generate_video` for tests.
7. **Verify the pixel before scaling.** Confirm the pixel/Events API fires and conversions report into
   Ads Manager before raising budget; scaling on broken measurement burns money blind.

## File the deliverable and record it
8. **Record spend and results.** `record_metric` spend, CPA, ROAS, and CTR; `save_file` (category
   `artifact`) the creative and campaign report with the campaign link. Never report un-fetched numbers.
9. **Recap and hand off.** `write_memory` (type `result`) what won and what fatigued; `report_result`,
   and `dispatch_task` for the next creative batch or budget change.

## Definition of done
- TikTok Ads confirmed connected; budget and external-comms sign-off cleared before launch.
- Spark-led, broad-targeted, pixel-verified campaign live with a creative-refresh cadence set.
- Spend and performance pulled from the real account, filed, recorded, and handed off.

## Common failure modes
- **Phantom campaign.** Claiming ads are live when the account was never connected — escalate instead.
- **Spending past the gate.** Launching without `request_budget` or sign-off, blowing the metered budget.
- **Set-and-forget creative.** Letting fatigued ads run as CPA quietly doubles — rotate on a cadence.
