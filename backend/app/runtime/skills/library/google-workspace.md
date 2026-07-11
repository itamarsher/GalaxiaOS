---
name: google-workspace
title: Google Workspace
description: Create, organize, or share Docs, Sheets, Drive files, or Gmail on the company's real Google Workspace when work needs to live where humans can open it.
roles: ceo, platform
---
# Google Workspace

Google Workspace is the company's real document layer — Docs, Sheets, Drive, Gmail — that humans open and
edit. Sending mail from it is **outbound, indexed comms**; use `send_email` / `send_notification` for the
ABOS-native path and Gmail only to reach real inboxes. The ABOS-adapted principle: **connect it as a tool
first, never assume it's wired**, then organize so access is by-role, not by-accident.

## Connect before you touch files
1. **Find the tool.** `discover_tools` with query `google workspace` (or `drive`, `gmail`); it exposes as
   `mcp__google_drive__*`, `mcp__gmail__*`, etc. Load what you need with `use_tool`.
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Workspace in
   Settings (MCP server or OAuth). Never invent a Drive link or claim a doc exists — a phantom file is worse
   than none.
3. **Egress + outbound gate.** Files and mail carry company data to a third party; `check_compliance` /
   `list_data_policies` before sensitive data flows, and respect the sign-off gate on any Gmail send.

## Organize for least privilege
4. **Shared drives, not My Drive.** Team content lives in shared drives so it survives the creator leaving.
   Files inherit the drive's membership — one home per team, not scattered personal folders.
5. **Grant access via Groups, least privilege.** Share to a Google Group by role, not named individuals; give
   the lowest tier that works (Viewer < Commenter < Editor; Content Manager, not Manager, by default). Access
   then follows role changes automatically instead of rotting into orphaned shares.
6. **Name on a convention.** Consistent, sortable names — `2026_Q3_ProjectPlan` — and set external-sharing
   defaults at the org/OU level rather than per file. Avoid link-sharing "anyone with the link" for anything
   non-public.

## File the deliverable and record it
7. **Record + link.** `write_memory` (type `result`) the file link and what shipped; `save_file` an export
   (category `artifact` or `financial`) so the durable copy lives in the fleet's store, not just Drive.

## Definition of done
- Workspace confirmed connected (or escalated, never faked); egress and mail gates respected.
- Content in a shared drive, access by Group at least privilege, names on-convention.
- Outcome recorded and any export filed.

## Common failure modes
- **Phantom file.** Claiming a doc exists when Workspace was never connected — escalate instead.
- **Over-sharing.** "Anyone with the link" or Editor-for-all, leaking data and losing the audit trail.
- **My-Drive orphans.** Team work owned by one account that vanishes when that person offboards.
