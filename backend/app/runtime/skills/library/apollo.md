---
name: apollo
title: Apollo.io
description: Build a prospect list, enrich contact data, or run outbound sequences in Apollo.io when sourcing and reaching cold prospects at scale.
roles: growth
---
# Apollo.io

Apollo.io is the fleet's prospecting and enrichment engine — a B2B contact database plus native
sequencing. This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never
assume it's wired**, then prospect precisely and send compliantly. Enriched contacts land in the ABOS
CRM (`crm_save_contact`, `log_lead`) as the durable record — Apollo is the source, CRM is the truth.

## Connect before you prospect
1. **Find the tool.** `discover_tools` with query `apollo`; it exposes as `mcp__apollo__*` once it's connected (by you or the founder). Load what you need with `use_tool` (search people, enrich, add to sequence).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Apollo in
   Settings (API key or MCP server). Never invent contacts, emails, or "sent" counts — a fabricated
   prospect list poisons the CRM and the forecast.
3. **Least privilege + egress.** Pushing company data into Apollo is data egress; if sensitive data
   flows out, `check_compliance` / `list_data_policies` first.

## Prospect precisely and protect deliverability
4. **Stack filters for a tight ICP.** Combine firmographics with title/seniority, keywords, and intent
   signals rather than one broad filter — precision beats volume. Save the segment so it's repeatable.
5. **Enrich and verify before you send.** Use enrichment to fill emails/phones, and only mail
   verified addresses; lean on Apollo's bounce check but treat fragile deliverability as a hard stop.
   Dedupe against existing CRM contacts with `crm_find_contacts` before importing.
6. **Sequences are gated external comms.** Any outbound sequence is indexed into the external-comms log
   and may need founder sign-off — respect the approval gate, don't route around it. `check_compliance`
   for opt-out/CAN-SPAM/GDPR before launch; warm the domain and keep daily volume conservative to
   protect sender reputation.
7. **Personalize the opener, keep it short.** Generic blasts tank reply rates and reputation together.

## File the deliverable and record it
8. **File the list + campaign.** `save_file` the prospect list export (category `artifact`) and
   `crm_save_contact` / `log_lead` each verified prospect into the CRM with source noted.
9. **Record + hand off.** `write_memory` (type `result`) the segment and outcome; `record_metric` for
   replies/meetings booked; `report_result` or `schedule_followup` on warm replies.

## Definition of done
- Apollo confirmed connected (or escalated, never faked); egress checked.
- Tight ICP filters, verified emails only, deduped against CRM; sequence passed the approval + compliance gate.
- Verified prospects saved to CRM; metrics recorded; nothing fabricated.

## Common failure modes
- **Phantom prospects.** Inventing contacts or "emails sent" when Apollo was never connected — escalate.
- **Spraying unverified emails.** Bounces and spam traps that burn the sending domain for everyone.
- **Skipping the comms gate.** Launching a cold sequence without compliance check or sign-off.
