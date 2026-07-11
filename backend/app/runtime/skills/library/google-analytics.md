---
name: google-analytics
title: Google Analytics 4
description: Configure events and key events, build explorations, or pull traffic and conversion data in GA4 when the company's web analytics live in Google Analytics 4.
roles: growth, data
---
# Google Analytics 4

GA4 is where the fleet reads what actually happens on the site — events, key events (conversions),
funnels, and attribution. This skill is the ABOS-adapted path to using it well: **connect it as a tool
first, never assume it's wired**, then measure so the numbers are real, current, and defensible.

## Connect before you read
1. **Find the tool.** `discover_tools` with query `google analytics`; it exposes as `mcp__google-analytics__*`
   (Data/Admin API) once the founder has connected it. Load what you need with `use_tool` (run a report,
   list events, read a metric).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect GA4 in Settings
   (MCP server or service-account/OAuth). Never invent a session count, conversion rate, or trend — a
   fabricated analytics number is the worst possible deliverable.
3. **Least privilege + egress.** GA4 exposes user-behavior data; pulling it out is egress. `check_compliance`
   / `list_data_policies` if user-level data leaves the platform.

## Measure so the numbers hold up
4. **Key events, chosen deliberately.** Everything is an event; mark only the handful that matter as **key
   events** (conversions). Three to five strong ones beat twenty noisy ones — a bloated conversion list
   makes every report ambiguous.
5. **Explorations for real questions.** Standard reports for monitoring; use **Explore** (funnel, path,
   segment overlap) to answer a specific "why did X drop" question. Save and name explorations so they're
   reusable, not one-off.
6. **Attribution + consent are load-bearing.** Prefer data-driven attribution over last-click. Confirm
   Consent Mode is live — without it, denied-consent traffic goes dark and modeled data is missing; a broken
   consent setup silently understates conversions.
7. **Never fabricate — read or escalate.** Every figure you report must come from a real GA4 query via
   `mcp__google-analytics__*` or `read_metrics`. If the data isn't there (sampling, retention window, not
   connected), say so and escalate — do not estimate.

## File the deliverable and record it
8. **File the analysis.** `save_file` (category `artifact`) the report/export with the GA4 property and date
   range in the description — undated analytics numbers are useless.
9. **Record + hand off.** `record_metric` the real figures, `write_memory` (type `result`) the finding,
   `dispatch_task` any follow-up (e.g. growth acting on a leaky funnel), then `report_result`.

## Definition of done
- GA4 confirmed connected (or escalated, never faked); user-data egress checked.
- Key events deliberate, explorations saved/named, attribution + Consent Mode verified.
- Every reported number sourced from a real query; analysis filed with property and date range.

## Common failure modes
- **Fabricated numbers.** Reporting a conversion rate you didn't query — read real data or escalate, always.
- **Key-event bloat.** Marking everything a conversion, so no report means anything.
- **Consent blind spot.** Trusting totals while Consent Mode is misconfigured and data is silently missing.
