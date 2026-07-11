---
name: reddit-ads
title: Reddit Ads
description: Run paid acquisition on Reddit — community/interest targeting, native-voice ad copy, or setting up conversion tracking for a Reddit campaign.
roles: growth
---
# Reddit Ads

Reddit is a community-native channel with a finely tuned BS detector: ads that sound like marketing
get ignored, ads that sound like a useful member post convert. This skill is the ABOS-adapted path —
**connect it as a tool first, never assume it's wired**, then treat every launch as metered spend that
clears the budget and external-comms gates before it goes live.

## Connect before you spend
1. **Find the tool.** `discover_tools` with query `reddit`; Reddit Ads exposes as `mcp__reddit-ads__*`
   once the founder has connected the ad account. Load what you need with `use_tool`.
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Reddit Ads
   Manager (MCP server or access token). Never invent a campaign, spend figure, or a live ad — a
   phantom campaign is worse than none.
3. **Clear the money and comms gates.** Ad spend is metered: `request_budget` before launch and
   `request_decision` for large or open-ended budgets. Ads are outbound external comms — indexed and
   may need founder sign-off. Don't route around the approval gate.

## Spend the way the community rewards
4. **Target 3-5 relevant communities, mid-tier first.** Start with a handful of on-topic subreddits;
   favor mid-size communities (roughly 100k-500k members) over the giants for comparable engagement at
   lower CPMs. Layer interest targeting and use Ads Manager's related-community suggestions to expand.
5. **Write like a member, not a brand.** Lead with something genuinely useful and transparent; run at
   least one text-heavy native post plus an image variation. Redditors sniff out astroturf and fake
   reviews instantly — respect the platform's tone or the spend is wasted.
6. **Wire the pixel before optimizing.** Install the Reddit Pixel (and Conversions API for server-side
   signal) before launch — without conversion data you can't optimize or retarget. Start on Lowest Cost
   bidding through the learning phase, then move to Cost Cap once you have a baseline CPA.
7. **Credit assisted conversions.** Reddit often drives conversions that complete later via another
   channel, so last-click undercounts it. `read_metrics` on assisted paths and brand-search lift before
   calling the channel dead.

## File the deliverable and record it
8. **Record spend and results.** `record_metric` spend, CPA, and CTR; `save_file` (category `artifact`)
   the ad copy and campaign report with the campaign link. Never report un-fetched numbers.
9. **Recap and hand off.** `write_memory` (type `result`) which communities and angles worked;
   `report_result`, and `dispatch_task` for the next creative or budget change.

## Definition of done
- Reddit Ads confirmed connected; budget and external-comms sign-off cleared before launch.
- Community-targeted, native-voice, pixel-tracked campaign live with a bidding plan.
- Spend and performance pulled from the real account, filed, recorded, and handed off.

## Common failure modes
- **Phantom campaign.** Claiming ads are live when the account was never connected — escalate instead.
- **Corporate voice.** Brand-speak ad copy that the community rejects — write like a member.
- **No pixel, no truth.** Launching without conversion tracking, so nothing can be optimized.
