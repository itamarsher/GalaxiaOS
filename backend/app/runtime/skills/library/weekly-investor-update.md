---
name: weekly-investor-update
title: Weekly Investor Update
description: Write the recurring investor/founder update from real company state.
roles: ceo, finance
---
# Weekly Investor Update

A tight, honest update a founder could forward to an investor. Grounded only in
real state — no spin, no invented traction.

## 1. Pull the real numbers
- `read_metrics` for the latest outcome signals and `read_financials` (or the
  budget view) for spend and runway. Use only measured values.

## 2. Structure it
Keep it to these sections, a few lines each:
- **TL;DR** — the one sentence that matters this week.
- **Progress** — what actually shipped or moved, tied to an objective.
- **Metrics** — the 2–4 numbers that matter, with the delta vs last period.
- **Spend & runway** — burn this period and projected runway.
- **Risks / asks** — what's at risk and anything you need from the founder.

## 3. Be honest about gaps
- If a metric didn't move, say so and say why. A flat week stated plainly beats a
  padded one.

## 4. File it
- Produce the update with `create_report` (kind `investor_update`). It is filed to
  the founder's Reports — it is NOT sent to anyone externally unless the founder
  later chooses to.
- `report_result` noting the update was filed.
