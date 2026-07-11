---
name: calendly
title: Calendly
description: Set up meeting booking, route inbound requests, or cut no-shows in Calendly when scheduling demos, intros, or calls with prospects and customers.
roles: growth, ceo
---
# Calendly

Calendly is the fleet's self-serve scheduling layer — reusable event types, availability rules,
routing forms, and reminder workflows. This skill is the ABOS-adapted path to using it well: **connect
it as a tool first, never assume it's wired**, then design event types that fill the calendar without
overrunning it. Booked meetings land in ABOS via `create_calendar_event` and the CRM
(`crm_log_activity`, `schedule_followup`).

## Connect before you schedule
1. **Find the tool.** `discover_tools` with query `calendly`; it exposes as `mcp__calendly__*` once it's connected (by you or the founder). Load what you need with `use_tool` (list event types, fetch a booking link).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Calendly in
   Settings (API key or MCP server). Never invent a booking link or claim a meeting is booked — a
   phantom link erodes trust instantly.
3. **Least privilege + egress.** Invitee details flowing through Calendly are data egress; if sensitive
   data is collected, `check_compliance` / `list_data_policies` first.

## Design event types that protect the calendar
4. **One event type per meeting kind.** Separate demo, intro, and support event types, each with its
   own duration, questions, and availability — don't overload a single generic link.
5. **Buffers, limits, and increments.** Add before/after buffers for prep and notes, cap daily meetings
   to preserve focus time, and set sane start-time increments. Availability rules are what keep the
   fleet from booking itself into the ground.
6. **Route inbound with forms + questions.** Use routing forms to send each invitee to the right event
   type/owner, and invitee questions to capture use-case and pain before the call, so it starts warm.
7. **Reminders and reconfirmation cut no-shows.** Configure Workflows for email/SMS reminders,
   reconfirmation requests, and no-show follow-ups — these are the single biggest lever on show rate.

## File the deliverable and record it
8. **Mirror the booking.** On a confirmed booking, `create_calendar_event` and `crm_log_activity` the
   meeting against the contact; `save_file` the event-type config (category `artifact`) if it's a setup deliverable.
9. **Record + hand off.** `write_memory` (type `result`) the scheduling setup; `record_metric` for
   meetings booked and show rate; `schedule_followup` for no-shows, or `report_result`.

## Definition of done
- Calendly confirmed connected (or escalated, never faked); invitee-data egress checked.
- Distinct event types with buffers/limits; routing + intake questions in place; reminder/reconfirm workflows on.
- Bookings mirrored to calendar + CRM; show-rate metric recorded; nothing fabricated.

## Common failure modes
- **Phantom link.** Sharing a booking link or "booked" meeting when Calendly was never connected — escalate.
- **No buffers or caps.** Back-to-back bookings with no prep time that burn the fleet out.
- **No reminders.** Skipping reconfirmation/reminder workflows, so no-shows quietly pile up.
