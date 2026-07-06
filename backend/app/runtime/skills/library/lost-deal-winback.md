---
name: lost-deal-winback
title: Lost Deal Win-back
description: Systematically revisit closed-lost deals when something has changed that makes them winnable again.
roles: growth, ceo
---
# Lost Deal Win-back

A lost deal is a warm lead with context. This playbook re-approaches past losses when a
real trigger has changed the math — not on a generic schedule.

## Trigger-first rule
Only re-approach when something changed: a new feature that fixes their stated blocker, a
competitor they chose faltering, a pricing change, a new champion, or a fresh funding/expansion
signal. No trigger → no touch. Re-approaching without a reason repeats the loss.

## Workflow
1. **Find winnable losses.** `crm_list_deals` for closed-lost; `crm_contact_timeline` for
   the original loss reason (this is why loss reasons must be logged — see `deal-pipeline-review`).
2. **Match trigger to loss reason.** Only pursue deals whose original blocker the trigger
   actually removes. Confirm the trigger with `web_search` if it's about their company.
3. **Re-establish contact** with a short, specific note: "when we last spoke, X blocked us;
   that's changed because Y — worth 15 minutes?" Send via `send_email`; `crm_log_activity`.
4. **Reopen properly.** If they engage, `update_deal` to a fresh discovery stage — don't
   assume old discovery still holds; re-verify pain and budget.
5. **Measure.** `record_metric` for win-back attempts and revival rate; `write_memory`
   (type `learning`) which triggers actually revive deals.

## Decision framework — pursue or leave
Pursue only if you can state, in one sentence, what changed and why it removes their
original objection. If you can't, leave it; a random re-touch just re-confirms the "no."

## Definition of done
- Every re-approach tied to a specific, verified trigger that addresses the loss reason.
- Reopened deals sent back through fresh discovery, not resumed mid-funnel.
- Win-back rate by trigger type recorded.

## Common failure modes
- **Scheduled re-touches with no trigger.** Annoying and low-yield.
- **Assuming old discovery holds.** Budgets, people, and priorities move; re-verify.
- **Ignoring the loss reason.** If you don't fix why they left, they leave again.
