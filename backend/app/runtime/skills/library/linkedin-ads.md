---
name: linkedin-ads
title: LinkedIn Ads
description: Launch or optimize B2B paid campaigns in LinkedIn Campaign Manager when the fleet is spending real money to reach professionals, run ABM, or capture leads.
roles: growth
---
# LinkedIn Ads

LinkedIn Ads is how the fleet buys precise B2B reach — by job title, seniority, company, and account
lists — for ABM and lead gen. This skill is the ABOS-adapted path to running it well: **connect it
as a tool first, never assume it's wired**, and because LinkedIn CPCs run high, **meter the budget
and clear the spend before you launch.**

## Connect and clear budget before you launch
1. **Find the tool.** `discover_tools` with query `linkedin ads`; it exposes as `mcp__linkedin-ads__*`
   once the founder has connected it. Load what you need with `use_tool` (create campaign, upload audience,
   pull stats).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect LinkedIn in
   Settings (Campaign Manager/API). If it can't exist yet, `request_capability`. Never invent a campaign,
   lead count, or CPL — a phantom result is worse than none.
3. **Budget + gate first.** Ad spend is metered and LinkedIn is expensive (CPCs often $7+ in SaaS) —
   `request_budget` before launching, and material spend may need `request_decision`. Ad copy and lead
   forms are external comms behind the approval gate; respect it.

## Structure so the spend converts
4. **Pick the objective for the funnel stage.** Awareness / Consideration (website visits, engagement) /
   Conversions (lead gen). Objective drives optimization — match it to what you actually want.
5. **Target on high-signal combinations.** Layer job function + seniority + company size, or upload a
   target account list to Matched Audiences (expect ~70-85% match) and target Director+ buyers. Layer
   seniority on top. Use Lookalikes to expand off your best converters.
6. **Prefer native Lead Gen Forms.** They convert roughly 2x better than off-site landing pages;
   a realistic CPL band is ~$75-150. Retarget site visitors via the Insight Tag.
7. **Watch the benchmarks.** CTR hovers ~0.5%; Thought Leader Ads run far cheaper CPC than single-image.
   If CPL blows past band, tighten targeting or change format before pouring in more budget.

## Track the spend and record it
8. **Report spend and results honestly.** Pull real numbers with `use_tool`, `record_metric` for
   spend / CPL / lead quality, and `read_financials` context so spend stays inside budget.
9. **Record + hand off.** `write_memory` (type `result`/`learning`) what converted; route captured leads
   with `log_lead` / `crm_save_contact`; `create_report`, or `report_result`.

## Definition of done
- LinkedIn connected (or escalated, never faked); budget requested and spend metered.
- Objective matched to funnel; high-signal targeting or ABM list; Lead Gen Forms where possible.
- Real metrics recorded; leads routed; outcome reported inside budget.

## Common failure modes
- **Phantom leads.** Claiming leads or CPL that don't exist — escalate instead.
- **Broad and expensive.** Loose targeting on a high-CPC platform, so budget burns with no pipeline.
- **Set-and-forget budget.** Not metering or requesting budget, so spend runs past the approved cap.
