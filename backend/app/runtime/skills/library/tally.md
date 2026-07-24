---
name: tally
title: Tally
description: Build a waitlist, lead-capture, or lightweight form in Tally when you need a fast, free public form with a shareable link.
roles: growth, product
---
# Tally

Tally is the fleet's fast path for a free, no-frills public form — a waitlist, a lightweight
lead-capture page, a quick intake. This skill is the ABOS-adapted path to using it well: **connect
it as a tool first, never assume it's wired**, then build, confirm, and test before you ever call a
form "live."

## Connect before you build
1. **Find the tool.** `discover_tools` with query `tally`; it exposes as `mcp__tally__*` once it's
   connected (by you or the founder). Load what you need with `use_tool` (create a form, configure
   fields, read submissions).
2. **Not connected? Connect it yourself — don't fake it.** Sign up for the service and self-issue an
   API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the
   token) so its tools come online for you on the next step, no founder needed. Only if you genuinely
   can't get credentials — it needs the founder's identity, payment, or a login only they have —
   `request_user_action` for the founder to connect Tally in Settings. If it can't exist yet,
   `request_capability`. Never invent a form link or fabricate submission data — a phantom waitlist
   is worse than none.
3. **Collecting submissions is data egress.** A public waitlist form gathers personal data (email,
   company) from real people; `check_compliance` / `list_data_policies` before publishing one, and
   collect only what you'll use.

## Build for exactly what's asked
4. **Required vs. optional is a contract, not a suggestion.** Mark only the fields the spec calls
   required (typically email and company); leave the rest — role, use case, team size, willingness
   to pay — genuinely optional so the form doesn't lose signups over a nice-to-have.
5. **Configure both confirmation messages.** Tally splits the on-submit confirmation into an
   on-page message (shown immediately) and an email confirmation (sent to the respondent) — set both
   explicitly rather than leaving Tally's defaults, since the defaults don't carry your product's voice
   or next-step instructions.
6. **Test end-to-end before calling it live.** Submit the form yourself (or via the tool) and verify
   the on-page message renders, the confirmation email arrives, and the submission lands in Tally —
   catching a broken confirmation step after launch costs signups you can't recover.
7. **Generate and verify the public URL.** Publish the form, pull the public share link via the tool,
   and confirm it loads unauthenticated before handing it off — a link that requires login isn't a
   waitlist link.

## Route responses, file, and record it
8. **Wire submissions somewhere durable.** Push new submissions via webhook/native integration into
   the CRM (`crm_save_contact`/`log_lead`) or a sheet so signups don't just sit in Tally. Sharing the
   form link externally is gated external comms — indexed and possibly sign-off-gated; route through
   the gate.
9. **File and record on real data only.** Read actual submissions via the tool; `save_file` (category
   `artifact`) the public URL and field config; `write_memory` (type `learning`) anything non-obvious
   about the setup; `record_metric` real signup count, or `report_result`.

## Definition of done
- Tally confirmed connected (or escalated, never faked); submission-collection egress checked.
- Fields match the required/optional spec exactly; both confirmation messages configured and tested.
- End-to-end submission verified; public URL confirmed live and unauthenticated.
- Submissions routed to CRM/sheet; only real data reported; results filed and outcome recorded.

## Common failure modes
- **Fabricated URL or submissions.** Reporting a live form or signup count when Tally was never
  connected, configured, or tested.
- **Wrong required fields.** Marking optional fields required (or vice versa), which either blocks
  signups or silently drops data the spec asked for.
- **Untested confirmations.** Shipping without checking the on-page message and email confirmation
  actually fire, so respondents get silence instead of a next step.
