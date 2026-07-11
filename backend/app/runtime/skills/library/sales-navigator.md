---
name: sales-navigator
title: LinkedIn Sales Navigator
description: Research accounts and decision-makers, build lead lists, or track buyer intent in LinkedIn Sales Navigator when sourcing B2B prospects and account signals.
roles: growth, research
---
# LinkedIn Sales Navigator

Sales Navigator is the fleet's account-and-people research layer — 40+ advanced filters, lead lists,
intent signals, and job-change alerts. This skill is the ABOS-adapted path to using it well: **connect
it as a tool first, never assume it's wired**, then turn signals into tracked leads. Qualified people
land in the ABOS CRM (`crm_save_contact`, `log_lead`) — Sales Navigator is the source, CRM is the truth.

## Connect before you search
1. **Find the tool.** `discover_tools` with query `sales navigator`; it exposes as
   `mcp__sales_navigator__*` once the founder has connected it. Load what you need with `use_tool`
   (run a lead search, read a list).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect it in
   Settings (LinkedIn account/API or MCP server). Never invent profiles, titles, or intent signals —
   fabricated research misroutes the whole outbound effort.
3. **Least privilege + egress.** Exporting profile data downstream is data egress; if it flows to a
   third party, `check_compliance` / `list_data_policies` first, and respect LinkedIn's terms (no
   scraping/automation that violates them).

## Turn filters into a tracked lead list
4. **Stack filters for a real ICP.** Combine seniority/title with firmographics and high-signal
   filters — "changed jobs in 90 days" (new execs buy 3x more) and company growth/hiring signals beat
   any single broad filter.
5. **Save searches to get alerts.** Save the search so new matches surface automatically; save
   multiple leads per account to watch the whole buying committee, and act on job-change and
   growth alerts promptly.
6. **Use Buyer Intent to prioritize.** On Advanced plans, work accounts already showing intent first —
   momentum plus a warm signal converts far better than cold.
7. **InMail is scarce and gated.** Credits are limited (~50/mo); an InMail is outbound external comms —
   it's indexed and may need sign-off, so respect the approval gate and personalize each one.

## File the deliverable and record it
8. **File the list + leads.** `save_file` the account/lead research (category `artifact`) and
   `log_lead` / `crm_save_contact` qualified people with the signal that flagged them.
9. **Record + hand off.** `write_memory` (type `result`) the target list and signals; `dispatch_task`
   growth to run outreach, or `report_result`.

## Definition of done
- Sales Navigator confirmed connected (or escalated, never faked); egress + LinkedIn terms checked.
- ICP built from stacked high-signal filters; search saved with alerts; intent used to prioritize.
- Qualified leads saved to CRM with their signal; InMail (if used) passed the comms gate; nothing fabricated.

## Common failure modes
- **Phantom research.** Inventing profiles or intent when Sales Navigator was never connected — escalate.
- **One flat filter.** A broad title-only search that surfaces noise instead of an ICP.
- **Ignoring the signals.** Saving leads but never acting on job-change, growth, or intent alerts.
