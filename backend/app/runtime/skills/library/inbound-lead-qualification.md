---
name: inbound-lead-qualification
title: Inbound Lead Qualification
description: Score and route inbound leads consistently so the fleet spends time on the ones that can convert.
roles: growth, ceo
---
# Inbound Lead Qualification

Every inbound lead costs attention. This playbook turns a raw signup or reply into a
scored, routed record so the fleet works the winnable deals and politely defers the rest.

## When to use
- A new lead arrives (form fill, reply to outreach, demo request) and you must decide
  whether to invest sales effort now, nurture, or drop it.

## Qualification framework (BANT + fit)
Score each lead on five factors, 0–2 each (max 10):
- **Fit** — does their segment match our ICP? (Off-ICP = hard stop, drop regardless of score.)
- **Need** — is there an explicit problem we solve?
- **Authority** — is this person a decision-maker or a champion with access to one?
- **Budget** — any signal they can pay at our price point?
- **Timing** — is there a trigger event or deadline?

Routing by total: **8–10** work now, **4–7** nurture, **0–3** decline.

## Workflow
1. **Dedupe.** `crm_find_contacts` on the email/domain before creating anything — never
   double-work a lead already in the pipeline. If they exist, `crm_contact_timeline` to
   see history and pick up where it left off.
2. **Enrich only from real sources.** Use `web_search` to confirm company, role, and
   segment. Do not invent firmographics; if you can't confirm fit, mark it unknown.
3. **Score and record.** Create/update the contact with `crm_save_contact`, and
   `write_memory` (type `learning`) the score and the one reason that drove routing.
4. **Route.**
   - Work-now → `crm_save_deal` at stage `qualified` and start the `sales-discovery-call-prep` skill.
   - Nurture → `schedule_followup` and add to the newsletter list (see `email-newsletter`).
   - Decline → send a short, kind decline with `send_email`; log it with `crm_log_activity`.
5. **Measure.** `record_metric` for leads scored, qualified rate, and time-to-first-touch.

## Definition of done
- Lead deduped, scored on the 5-factor rubric, and routed to exactly one path.
- The routing decision and its single driving reason are in memory.
- Time-to-first-touch recorded.

## Common failure modes
- **Chasing off-ICP leads** because they replied fast. Fit is a gate, not a score to average away.
- **Fabricating firmographics** to justify a score. Unknown is a valid, honest input.
- **Silent drops.** A one-line decline preserves reputation and future re-engagement.
