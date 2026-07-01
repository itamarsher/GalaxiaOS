---
name: affiliate-program
title: Affiliate / Partner Program
description: Recruit and manage affiliates or resellers with clean tracking and payouts tied to real conversions.
roles: growth, finance
---
# Affiliate / Partner Program

An affiliate program extends reach through partners paid on performance. This playbook keeps
tracking clean, payouts honest, and partner quality high.

## Workflow
1. **Design the economics first.** Set commission rate and attribution window so payouts stay
   inside margin — model it with `read_financials` and `request_decision` from finance. A
   program that pays more than the customer is worth is a slow bleed.
2. **Recruit the right partners.** Target partners whose audience is your ICP (see
   `influencer-partnership` vetting). Quality over quantity; one aligned partner beats fifty spammy ones.
3. **Terms and compliance.** Define what's allowed (no brand-bidding, required "#ad" disclosure,
   no spam). `check_compliance` on disclosure; `flag_legal_risk` on unusual terms. Put it in writing.
4. **Instrument attribution.** Give each partner a unique tracked link/code so conversions are
   attributable. Log partner-sourced leads with `log_lead` and deals with `crm_save_deal`.
5. **Pay on verified conversions only.** Reconcile claimed vs. actual conversions before paying;
   process payouts through `record_transaction`. Never pay on unverified numbers.
6. **Measure and prune.** `record_metric` for partner-sourced revenue and blended CAC; cut
   partners who don't convert or who violate terms. `write_memory` (type `learning`) what partner
   profile works.

## Decision framework — recruit or reject
Accept a partner only if their audience overlaps the ICP and they'll respect the terms. A
misbehaving affiliate damages the brand faster than they earn.

## Definition of done
- Commission modeled to protect margin; attribution instrumented; disclosure compliant.
- Payouts on verified conversions only; underperformers pruned.

## Common failure modes
- **Commission that breaks margin.** Model it before launch.
- **Paying unverified conversions.** Reconcile first.
- **Ignoring partner conduct.** Brand-bidding and spam cost more than the revenue.
