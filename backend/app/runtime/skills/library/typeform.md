---
name: typeform
title: Typeform
description: Build a survey, lead-capture form, or feedback flow in Typeform when you need high completion and clean, routed responses.
roles: growth, product
---
# Typeform

Typeform is the fleet's conversational form and survey builder — one question at a time, tuned for high
completion. This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never
assume it's wired**, then design for completion and never invent the responses that come back.

## Connect before you build
1. **Find the tool.** `discover_tools` with query `typeform`; it exposes as `mcp__typeform__*` once it's connected (by you or the founder). Load what you need with `use_tool` (create a form, read responses, wire webhooks).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Typeform in
   Settings (MCP server or API token). If it can't exist yet, `request_capability`. Never invent a form
   link or fabricate response data — a phantom survey is worse than none.
3. **Collecting responses is data egress.** A live form gathers personal data from real people;
   `check_compliance` / `list_data_policies` before publishing one, and collect only what you'll use.

## Design for completion
4. **Keep it short — length kills completion.** Forms over 6 questions drop below 50% completion, and
   sub-one-minute forms complete ~15pts higher. Cut every non-essential question; one ask per screen.
5. **Use Logic Jumps to personalize.** Branch respondents down relevant paths so nobody answers
   questions that don't apply — relevance is what lifts completion, and it segments the data as it comes in.
6. **Hidden Fields for context you already have.** Pass known data (UTM/source, email, plan, contact id)
   through the form URL into Hidden Fields so responses arrive attributed — don't ask people what you know.
7. **A welcome screen without a question.** An opening screen that sets context (not a question) lifts
   completion ~5pts; give a clear reason to start before you ask anything.

## Route responses, file, and record it
8. **Wire integrations, don't copy-paste.** Push responses via webhook/native integration into the CRM
   (`crm_save_contact`/`log_lead`) or sheet so data flows automatically. Sending the form out to
   recipients is gated external comms — indexed and possibly sign-off-gated; route through the gate.
9. **File and record on real data only.** Read actual responses via the tool; `save_file` (category
   `artifact`) a results summary; `write_memory` (type `learning`) the insight; `record_metric` real
   completion rate and response count; `dispatch_task` follow-up, or `report_result`.

## Definition of done
- Typeform confirmed connected (or escalated, never faked); response-collection egress checked.
- Short, one-per-screen, Logic Jumps for relevance, Hidden Fields for attribution, non-question welcome.
- Responses routed to CRM/sheet; only real data reported; results filed and outcome recorded.

## Common failure modes
- **Fabricated responses.** Reporting survey results when Typeform was never connected or read.
- **Long flat form.** No logic and too many questions, so completion collapses and data is thin.
- **Unattributed leads.** Skipping Hidden Fields, so responses arrive with no source or contact context.
