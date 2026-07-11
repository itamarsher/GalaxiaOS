---
name: miro
title: Miro
description: Run a workshop, retro, or discovery session — or synthesize sticky notes and frameworks — on a shared Miro board, live or async.
roles: product, design
---
# Miro

Miro is the fleet's shared whiteboard for workshops, discovery, retros, and framework-driven synthesis.
This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's
wired**, then structure the board so it produces decisions, not a wall of orphaned sticky notes.

## Connect before you facilitate
1. **Find the tool.** `discover_tools` with query `miro`; Miro exposes as `mcp__miro__*` once it's connected (by you or the founder). Load what you need with `use_tool` (create a board, read frames/items).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Miro in
   Settings (MCP server or API token). If the capability can't exist yet, `request_capability`.
   Never invent a board link or claim notes were captured — a phantom board is worse than none.
3. **Least privilege + egress.** Boards carry company strategy; if anything sensitive lands on one,
   `check_compliance` / `list_data_policies` first.

## Structure the board so it produces decisions
4. **Start from a template, don't build a blank canvas.** Pull a proven framework from the 2,500+
   library (retro, Lean Inception, journey map, 2x2) — each ships with timing, facilitator prompts,
   and a flow. This is 30 seconds vs 15 minutes and gives participants an obvious path.
5. **Time-box with the timer; decide with voting.** Box each activity with the built-in timer, then use
   **anonymous dot voting** to converge — anonymity mitigates groupthink so the loudest voice doesn't win.
6. **Synthesize, don't just collect.** After divergence, cluster sticky notes into named themes and
   write a one-line takeaway per cluster. A board that ends as scattered notes produced nothing; the
   deliverable is the synthesis, not the raw ideation.
7. **Design for async too.** Add clear instructions and a Talktrack walkthrough so contributors in other
   time zones add input before and after any live session — the board is the durable workspace, not a
   one-off meeting artifact.

## File the deliverable and record it
8. **Export and file.** Export the synthesized board (or the decision frame) and `save_file`
   (category `artifact`) with the Miro link in the description — the file store is the durable,
   shareable source, not the agent's memory.
9. **Record + hand off.** `write_memory` (type `result`) the decisions and themes; `dispatch_task` the
   owners of any follow-up actions, or `report_result`.

## Definition of done
- Miro confirmed connected (or escalated, never faked); sensitive-data egress checked.
- Ran from a template, time-boxed, voted to converge, and clustered notes into named takeaways.
- Synthesis exported, `save_file`d with the link, decisions recorded and actions handed off.

## Common failure modes
- **Phantom board.** Claiming notes were captured when Miro was never connected — escalate instead.
- **Wall of orphaned notes.** Ideation with no clustering or vote, so no decision comes out.
- **Live-only thinking.** No instructions or async path, so remote contributors are locked out.
