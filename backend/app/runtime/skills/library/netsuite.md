---
name: netsuite
title: NetSuite
description: Work in NetSuite ERP — chart of accounts, subsidiaries, the period close, saved searches, or roles and permissions.
roles: finance
---
# NetSuite

NetSuite is the fleet's system of record — the ERP where the GL, subsidiaries, and the period close live.
The ABOS-adapted rule: **connect it as a tool first, never assume it's wired**, and because it is the
book of truth, **read real data and mirror it, never fabricate a balance or post an unapproved entry**.

## Connect before you post
1. **Find the tool.** `discover_tools` with query `netsuite`; it exposes as `mcp__netsuite__*` once the
   founder connects it. Load what you need with `use_tool` (read records, run saved search, post entry).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect NetSuite in
   Settings (token-based auth: account ID + keys). Never invent an account balance, journal, or report
   figure — a phantom number in the ERP is worse than none. If it can't exist yet, `request_capability`.
3. **Gate posting.** A journal entry or transaction changes the books; `request_decision` for material or
   irreversible postings, and confirm the treatment against `get_company_playbook`.

## Run the ERP the way pros do
4. **Keep the chart of accounts lean; use segments.** NetSuite is multi-dimensional — let Department,
   Class, Location, and Subsidiary carry the "where/why," not bloated GL accounts. Never bake a subsidiary
   or department into an account name.
5. **Respect the subsidiary structure.** Post to the right subsidiary and use elimination/consolidation as
   designed in OneWorld; a cross-subsidiary miscoding is painful to unwind.
6. **Close in order.** Lock A/R, lock A/P, lock all, then close the period. Once closed, don't reopen —
   only override-permitted roles change a closed period, so finish before locking.
7. **Saved searches over ad hoc pulls.** Build reusable saved searches for recurring reporting and reconcile
   from them; enforce least-privilege roles (separation of duties) so agents only get the access they need.

## Mirror it in ABOS and file it
8. **Read, don't guess.** `read_financials` and `record_transaction` mirror NetSuite's actual GL into the
   ledger; if a figure isn't in NetSuite, escalate with `request_user_action` rather than estimate.
9. **File reports.** `save_file` exported financials and close packages (category `financial`) with the
   saved-search/report link; `write_memory` (type `result`), `create_report`, `report_result`. Tax:
   `check_compliance`.

## Definition of done
- NetSuite confirmed connected (or escalated, never faked); material postings decided, not silent.
- Lean COA with segments, correct subsidiary, close done in lock order, least-privilege roles.
- GL mirrored via `read_financials`/`record_transaction`, close package `save_file`d (financial).

## Common failure modes
- **Phantom figure.** Reporting a balance or entry NetSuite was never connected to return — escalate instead.
- **Segment in the COA.** Encoding subsidiary/department into accounts, bloating the chart and reporting.
- **Reopening a closed period.** Editing a locked period and breaking the audited close.
