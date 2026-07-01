---
name: upsell-and-crosssell
title: Upsell & Cross-sell
description: Grow revenue from existing customers by matching expansion offers to demonstrated need and usage.
roles: growth, product
---
# Upsell & Cross-sell

Expansion revenue is cheaper than new logos and signals product love. This playbook finds
expansion moments from real usage and offers value, not pressure.

## Workflow
1. **Find the signal.** `read_metrics` / `cohort-analysis` for accounts hitting limits, using
   power features, or showing growth. Expansion offers should follow demonstrated need, not a quota.
2. **Match offer to need.** Map each signal to the right offer (higher tier, add-on, seats). An
   offer that doesn't solve a felt problem is noise. Confirm the offering exists (`get_company_playbook`).
3. **Time it right.** Reach out at a value moment (after a win, at a usage ceiling) — not right
   after a support complaint. `crm_contact_timeline` for context.
4. **Frame as value.** Lead with the outcome the upgrade unlocks, backed by their own usage data.
   `draft_document` / `send_email` a short, specific offer.
5. **Handle the deal.** `crm_save_deal` for the expansion; if pricing/terms are non-standard,
   `proposal-and-quote`. Process new charges via `record_transaction`.
6. **Measure.** `record_metric` for expansion revenue and net revenue retention; `write_memory`
   (type `learning`) which signals predict successful expansion.

## Decision framework — offer or wait
Offer only when usage shows the customer would genuinely benefit. Pushing upgrades on customers
who aren't ready drives churn and erodes trust — the opposite of the goal.

## Definition of done
- Expansion signals sourced from real usage; offer matched to demonstrated need and timed well.
- Expansion revenue / NRR recorded; predictive signals banked.

## Common failure modes
- **Quota-driven pushing.** Offers untethered to need feel like pressure and churn customers.
- **Bad timing.** Upselling an unhappy customer backfires.
- **Ignoring net revenue retention.** Expansion that triggers churn isn't growth.
