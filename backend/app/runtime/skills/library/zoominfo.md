---
name: zoominfo
title: ZoomInfo
description: Prospect with intent data, run advanced searches, verify contact accuracy, or export leads from ZoomInfo — where B2B contact data is GDPR-sensitive egress.
roles: growth, research
---
# ZoomInfo

ZoomInfo is the fleet's B2B contact and intent database — firmographics, buying signals, and verified
emails to target the right accounts. This skill is the ABOS-adapted path to using it well: **connect it
as a tool first, never assume it's wired**, and treat every export as regulated data egress, because
exported contacts are personal data governed by GDPR/CCPA. ABOS's `crm_*` tools remain the source of truth.

## Connect before you search
1. **Find the tool.** `discover_tools` with query `zoominfo`; it exposes as `mcp__zoominfo__*` once the
   founder has connected it. Load what you need with `use_tool` (search, enrich, export).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect ZoomInfo in
   Settings (MCP server or API key). Never invent contacts, emails, or intent scores — fabricated leads
   poison outreach and burn sender reputation.
3. **Egress is the gate, not an afterthought.** Exporting contact data is GDPR/CCPA-sensitive egress:
   `check_compliance` / `list_data_policies` before export, and `flag_legal_risk` if a region or use case
   is doubtful. ZoomInfo processes EU data under legitimate interest — respect suppression requests.

## Search and enrich with precision
4. **Narrow topics beat broad ones.** For intent, pick 5-10 specific topics ("cloud security compliance"),
   not 50 vague ones ("cybersecurity") — specificity is what lifts signal-to-noise. Save the search.
5. **Stack filters, then layer intent.** Combine firmographic, technographic, and location filters in
   Advanced Search, then overlay intent by signal score, audience strength, and spike so you contact
   accounts that are both a fit and in-market. Use streaming intent for real-time signals.
6. **Verify before you trust.** Data drifts and exports sometimes fan out to every employee; sanity-check
   accuracy, dedupe against `crm_find_contacts`, and enrich only the fields you'll act on — don't hoard.

## File the deliverable and record it
7. **Export tight, file, and load.** Export a named, filtered list (not a raw dump); `save_file` (category
   `artifact`) with the search criteria noted, then `crm_save_contact`/`log_lead` the qualified rows into
   ABOS as the system of record.
8. **Record + hand off.** `record_metric` list size and match rate, `write_memory` (type `result`) the ICP
   that worked, then `report_result` or `dispatch_task` the outreach.

## Definition of done
- ZoomInfo confirmed connected (or escalated, never faked); export screened for GDPR/CCPA egress.
- Specific intent topics and stacked filters used; accuracy verified and deduped against the CRM.
- List exported, `save_file`d, qualified contacts loaded to ABOS CRM, outcome recorded.

## Common failure modes
- **Ungated export.** Egressing personal data with no compliance check — a regulatory and reputational hit.
- **Phantom leads.** Inventing contacts or intent scores when ZoomInfo was never connected — escalate.
- **Broad-topic noise.** Fifty vague intent topics that surface everyone and qualify no one.
