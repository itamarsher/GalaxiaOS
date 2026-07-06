---
name: sales-followup-cadence
title: Sales Follow-up Cadence
description: Run a persistent-but-respectful follow-up sequence that revives deals without burning goodwill.
roles: growth, ceo
---
# Sales Follow-up Cadence

Most deals are lost to silence, not to "no." This playbook is a structured multi-touch
cadence that adds value each time and knows when to stop.

## The cadence (value-add, not nagging)
A default 5-touch sequence over ~3 weeks; each touch gives before it asks:
1. **Day 0** — recap + agreed next step (`send_email`).
2. **Day 3** — a relevant resource or answer to an open question.
3. **Day 7** — a proof point (case, metric, comparison) tied to their pain.
4. **Day 14** — a light nudge with a specific, easy next step.
5. **Day 21** — the "break-up": permission to close the loop unless it's still live.

## Workflow
1. **Load state.** `crm_contact_timeline` to see what's been sent; never repeat a touch.
2. **Personalize each touch** to the pain and objection on record — no generic "just checking in."
3. **Send and log** with `send_email` + `crm_log_activity`; `schedule_followup` for the next
   touch date so the cadence self-advances.
4. **Read the signal.** A reply → advance the deal (`update_deal`). The break-up with no
   reply → mark the deal lost with a reason (`write_memory` type `learning`).
5. **Measure.** `record_metric` for reply rate and revival rate by touch number, so the
   cadence itself improves.

## Decision framework — when to stop
Stop at the break-up touch. Persistence past a clear signal of no-interest costs reputation
and future re-engagement. Silence after the break-up = a clean, logged loss, not a mystery.

## Definition of done
- Each touch personalized and value-adding; none repeated.
- Next touch scheduled or the deal cleanly closed with a reason.
- Reply/revival rates recorded.

## Common failure modes
- **"Just checking in."** Adds no value; trains the buyer to ignore you.
- **Infinite cadence.** No break-up = deals that never close in the CRM and skew forecasts.
- **Same message, new date.** Each touch must earn the open.
