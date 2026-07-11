---
name: google-ads
title: Google Ads
description: Launch, structure, or optimize paid search and Performance Max campaigns in Google Ads when the fleet is spending real money to acquire traffic or leads via Google.
roles: growth
---
# Google Ads

Google Ads is how the fleet buys intent-based traffic on search and Performance Max. This skill is
the ABOS-adapted path to running it well: **connect it as a tool first, never assume it's wired**,
and because every click spends real money, **meter the budget and clear the spend before you launch.**

## Connect and clear budget before you launch
1. **Find the tool.** `discover_tools` with query `google ads`; it exposes as `mcp__google-ads__*` once the
   founder has connected it. Load what you need with `use_tool` (create campaign, add keywords, pull stats).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Google Ads in
   Settings (OAuth/API). If it can't exist yet, `request_capability`. Never invent a campaign, click count,
   or conversion number — a phantom result is worse than none.
3. **Budget + gate first.** Ad spend is metered — `request_budget` before launching, and a large or
   ongoing spend may need `request_decision`. Ad copy and landing pages are external comms behind the
   approval gate; respect it.

## Structure so the spend converts
4. **Verify conversion tracking before spending a cent.** Google tag installed, conversions defined
   (lead/purchase/signup), GA4 linked, Enhanced Conversions + Consent Mode on. Spending without tracking
   is flying blind — non-negotiable.
5. **Structure by theme, tightly.** Separate campaigns per service/market; ad groups grouped by intent,
   not dozens of keywords dumped together. Tight groups lift ad relevance and Quality Score.
6. **Manage negatives continuously.** Build a shared negative-keyword list and update it from real search
   terms — required if you use broad match with Smart Bidding, and now supported at campaign level
   (up to 10k) even in Performance Max.
7. **Earn Quality Score on the landing page.** Landing-page experience and expected CTR carry the most
   weight; a dedicated page matching the ad's promise is the highest-leverage fix. For Performance Max,
   feed strong assets and add negatives — automation still needs guardrails.

## Track the spend and record it
8. **Report spend and results honestly.** Pull real metrics with `use_tool`, `record_metric` for
   spend / CPA / conversions, and `read_financials` context so spend stays inside budget.
9. **Record + hand off.** `write_memory` (type `result`/`learning`) what worked; `create_report` for the
   founder, or `report_result`.

## Definition of done
- Google Ads connected (or escalated, never faked); budget requested and spend metered.
- Conversion tracking verified; themed structure; negatives managed; Quality Score addressed.
- Real metrics recorded; outcome reported inside budget.

## Common failure modes
- **Phantom campaign.** Claiming a campaign or conversions that don't exist — escalate instead.
- **Spending untracked.** Launching with no conversion tracking, so optimization is guesswork.
- **Set-and-forget budget.** Not metering or requesting budget, so spend runs past the approved cap.
