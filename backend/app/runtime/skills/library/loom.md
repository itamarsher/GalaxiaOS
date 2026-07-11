---
name: loom
title: Loom
description: Record an async video update, walkthrough, or demo in Loom instead of a meeting or a wall of text — and share it out.
roles: product, growth
---
# Loom

Loom is how the fleet replaces meetings and long docs with short async video — updates, demos,
walkthroughs, feedback. This skill is the ABOS-adapted path to using it well: **connect it as a tool
first, never assume it's wired**, then make videos that get watched and drive one clear next step.

## Connect before you record
1. **Find the tool.** `discover_tools` with query `loom`; Loom exposes as `mcp__loom__*` once the
   founder has connected it. Load what you need with `use_tool` (create/read a recording, get transcript).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Loom in
   Settings (MCP server or API key). If the capability can't exist yet, `request_capability`.
   Never invent a Loom link or claim a video exists — a phantom recording is worse than none.
3. **Least privilege + egress.** A recording can capture a screen full of sensitive data; if it might,
   `check_compliance` / `list_data_policies` first, and suppress anything that shouldn't leave.

## Record so it gets watched
4. **Lead with the point, keep it under 3 minutes.** State the ask in the first sentence, then support
   it. For anything longer, split into several short videos — attention drops off a single long take.
5. **Script loosely, then trim.** Sketch the beats before recording; afterward trim dead air and cut
   tangents in the middle. A tight edit signals the viewer's time was respected.
6. **One CTA, plus a written summary.** Add a single call-to-action button for the next step and put a
   short text summary in the description so viewers can decide whether to watch — and act without it.
7. **Use transcripts, chapters, and analytics.** Let auto-transcript make it searchable, add chapters
   for longer walkthroughs, and read view/engagement analytics to see if the message actually landed —
   never invent view counts or "everyone watched it."

## Share, file, and record it
8. **Sharing outbound is gated.** Sending a Loom outside the company is external comms — it's indexed
   into the external-comms log and may need founder sign-off. Respect the gate; don't route around it.
9. **File and record.** `save_file` (category `artifact`) the link and key transcript points;
   `write_memory` (type `result`) what was communicated and the CTA; `record_metric` real view/engagement
   numbers if tracking them; `dispatch_task` any follow-up, or `report_result`.

## Definition of done
- Loom confirmed connected (or escalated, never faked); on-screen sensitive-data egress checked.
- Under ~3 min, trimmed, one CTA, written summary; transcript/chapters on; real analytics read.
- Outbound share passed the comms gate; link filed, outcome recorded, follow-up handed off.

## Common failure modes
- **Phantom recording.** Claiming a video exists when Loom was never connected — escalate instead.
- **Rambling, no CTA.** A long unedited take with no ask, so nobody watches or acts.
- **Fabricated engagement.** Reporting views or "watched by all" without reading real analytics.
