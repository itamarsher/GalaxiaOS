---
name: cold-email-outreach
title: Cold Email Outreach Campaign
description: Plan and run a small, targeted cold-email outreach campaign end to end.
roles: growth, ceo
---
# Cold Email Outreach Campaign

A repeatable playbook for turning a hypothesis about a customer segment into a
small, measurable outreach campaign. Keep it small and instrumented — the goal is
to learn, not to blast.

## 1. Define the target and the bet
- Write down the specific segment you are targeting and *why* you believe they have
  the problem you solve. Record this as a `write_memory` of type `experiment`.
- Decide the single metric that proves the bet (e.g. reply rate ≥ 10%, ≥ 3 calls
  booked). State the target before you send anything.

## 2. Build the list
- Use `crm_find_contacts` to check who you already know; do not re-contact people
  already in the pipeline. Add new prospects with `crm_save_contact`.
- Keep the first batch deliberately small (10–25 contacts) so one iteration is
  cheap and the result is readable.

## 3. Write the message
- One clear value proposition, one specific ask (usually a 15-minute call). No
  attachments, no more than ~120 words.
- Personalize the opening line per contact based on something real.

## 4. Send and log
- Send with `send_email`. If it reports the capability is unsupported, STOP and
  `request_capability` — do not pretend mail was sent.
- Log each send as a CRM activity (`crm_log_activity`) and schedule a follow-up
  (`schedule_followup`) for ~3 business days out.

## 5. Measure and learn
- After replies land, `record_metric` the reply/booking counts against your target.
- `write_memory` a `result` capturing what worked, what didn't, and the next
  variant to try. Report the outcome with `report_result`.
