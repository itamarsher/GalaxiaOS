---
name: docusign
title: DocuSign
description: Send a contract, offer letter, or agreement out for legally-binding e-signature, or track an envelope through signing, in DocuSign.
roles: finance, ceo
---
# DocuSign

DocuSign turns a document into a legally-binding, tamper-evident signature transaction. Sending an envelope
is an **outbound, indexed, and legally consequential act** — it is gated. The ABOS-adapted principle:
**connect it as a tool first, never assume it's wired**, and **never send for signature without an explicit
decision** — an e-signature request binds the company.

## Connect and clear the gate before you send
1. **Find the tool.** `discover_tools` with query `docusign`; it exposes as `mcp__docusign__*` once connected.
   Load what you need with `use_tool` (create envelope, from template, list recipients).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect DocuSign in
   Settings. Never invent a signing link or claim a contract was sent — a phantom envelope is a legal liability.
3. **Gate the send.** Sending a contract for signature is binding and irreversible-in-effect: `request_decision`
   before it goes out, `check_compliance` on the terms, and `flag_legal_risk` if anything is unusual. Respect
   the external-comms approval gate.

## Send so it holds up
4. **Templates over one-offs.** Reuse an approved template for recurring agreements (NDAs, offer letters) so
   the language and field layout are already vetted — don't hand-place tabs on a fresh document each time.
5. **Set signing order deliberately.** Sequential routing when approvals must happen step-by-step; parallel
   when signers are independent and you want no bottleneck. Confirm every recipient's name and email and use
   Validate Fields before sending.
6. **Constrain fields and preserve the trail.** Add required tabs (signature, date, initials) and validated
   inputs (email, currency, regex masks) so signers can't submit bad data. Set reminders and an expiration.
   Keep the Certificate of Completion — it is the audit trail proving who signed, when, and where.

## File the deliverable and record it
7. **File the executed copy.** Once complete, `save_file` the signed PDF and Certificate of Completion
   (category `financial`), `write_memory` (type `result`) the envelope ID and status, and `report_result`.

## Definition of done
- DocuSign connected (or escalated, never faked); `request_decision` + compliance clear before send.
- Template used, signing order and recipients verified, fields validated, reminders/expiration set.
- Executed document + Certificate of Completion filed and outcome recorded.

## Common failure modes
- **Sending without sign-off.** Dispatching a binding contract with no `request_decision` — the company is
  now on the hook for terms nobody approved.
- **Phantom envelope.** Claiming a document was sent when DocuSign was never connected — escalate instead.
- **Wrong signing order.** Parallel routing on an approval chain, so a document is signed out of sequence.
