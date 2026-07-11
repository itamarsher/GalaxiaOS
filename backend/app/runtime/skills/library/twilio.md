---
name: twilio
title: Twilio
description: Send SMS, place voice calls, or run phone/OTP verification through Twilio — including sender registration, opt-out handling, and metered send cost.
roles: platform, growth
---
# Twilio

Twilio is how the fleet sends SMS, places calls, and verifies phone numbers. This skill is the
ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, then treat
every send as both metered spend and gated external comms — because it is both.

## Connect before you send
1. **Find the tool.** `discover_tools` with query `twilio`; it exposes as `mcp__twilio__*` once the
   founder has connected the account. Load what you need with `use_tool` (send a message, start a Verify
   check, read delivery status).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Twilio in
   Settings (MCP server or Account SID + auth token). If the capability can't exist yet,
   `request_capability`. Never claim a text was sent — a phantom send is worse than none.
3. **Metered + gated.** Every SMS costs money (US ~$0.0079/segment plus carrier surcharge) and is
   outbound external comms indexed for founder sign-off. `request_budget` before a campaign-scale send;
   `check_compliance` before messaging a list, and respect the approval gate — don't route around it.

## Send compliant, or carriers block you
4. **Register the sender first (US A2P 10DLC).** US application-to-person traffic needs a registered
   Brand and Campaign or carriers filter it. If the number isn't registered, `request_user_action` —
   don't blast from an unregistered long code and get the account flagged.
5. **Opt-in is required, opt-out is sacred.** Only message recipients who explicitly opted in per
   campaign. Honor STOP/UNSUBSCRIBE automatically and never message an opted-out number; the STOP
   confirmation must name the brand and confirm no further messages. Include an opt-out line in the
   first message.
6. **Use Verify, don't hand-roll OTP.** For phone/OTP verification use the Verify API rather than
   generating and storing codes yourself — it handles delivery, rate limits, and fraud. Validate every
   inbound webhook with the `X-Twilio-Signature` header so you don't act on spoofed callbacks.

## File the deliverable and record it
7. **Record the send.** `save_file` the message template/campaign (category `brand`) and `record_metric`
   for sent/delivered/opt-out counts — the send is logged to external comms, so keep the artifact durable.
8. **Record + hand off.** `write_memory` (type `result`) the campaign and spend; `report_result`, and
   `dispatch_task` growth for follow-up on replies.

## Definition of done
- Twilio confirmed connected (or escalated, never faked); budget requested and compliance checked.
- Sender registered (10DLC), recipients opted in, STOP honored, webhooks signature-validated.
- Send logged, template `save_file`d, delivery/opt-out metrics recorded.

## Common failure modes
- **Unregistered blast.** Sending US A2P from an unregistered number gets it carrier-filtered or banned.
- **Ignoring opt-out.** Messaging a STOP'd number is a legal and carrier violation — honor it every time.
- **Phantom send.** Claiming a text went out when Twilio was never connected — send it or escalate.
