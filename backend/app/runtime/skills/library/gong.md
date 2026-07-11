---
name: gong
title: Gong
description: Mine call recordings for deal risk, coaching, trackers, or forecast signal in Gong — where recording a conversation requires participant consent.
roles: growth
---
# Gong

Gong is the fleet's conversation-intelligence layer — it records and transcribes calls, then surfaces
deal risk, coaching moments, and forecast signal grounded in what buyers actually said. This skill is the
ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, and treat
recording as a consent-gated action before anything else. ABOS's `crm_*` deals stay the system of record.

## Connect before you listen
1. **Find the tool.** `discover_tools` with query `gong`; it exposes as `mcp__gong__*` once the founder has
   connected it. Load what you need with `use_tool` (read calls, trackers, deal insights).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Gong in
   Settings (MCP server or API key). Never invent a call, quote, or sentiment score — a fabricated insight
   corrupts the forecast it feeds.
3. **Consent is the first gate.** Recording requires participant consent; many US states are dual-party and
   GDPR demands explicit consent with fines up to 4% of revenue. `check_compliance` before enabling or
   analyzing recordings, and `flag_legal_risk` for any cross-border or unconsented call.

## Turn conversations into signal
4. **Read deal risk, then act.** Use deal warnings for stalled or gone-silent deals and reflect that health
   into `update_deal`/`crm_save_deal` — Gong is the early-warning system, ABOS is where the risk is logged.
5. **Trackers, not vibes.** Configure trackers for competitor mentions, pricing, and objections so patterns
   are countable across calls, not anecdotal. Forecast off buyer engagement and sentiment, not CRM guesses.
6. **Frame coaching as learning.** Surface winning call clips before performance data; pull objection-handling
   and discovery moments to coach reps. Position insights as enablement, never surveillance.

## File the deliverable and record it
7. **Export the takeaway and file.** Export the call summary, clip, or deal-risk report and `save_file`
   (category `artifact`) with the Gong link in the description — the durable source, not agent memory.
8. **Record + hand off.** `crm_log_activity` the call outcome, `record_metric` the tracked signal,
   `write_memory` (type `learning`) the pattern, then `report_result` or `dispatch_task` follow-up.

## Definition of done
- Gong confirmed connected (or escalated, never faked); recording consent verified via compliance.
- Deal warnings acted on and mirrored to ABOS deals; trackers configured; forecast grounded in conversation.
- Takeaway exported and `save_file`d, call outcome logged, learning recorded.

## Common failure modes
- **Recording without consent.** Analyzing a call that lacked lawful consent — a compliance breach, not a shortcut.
- **Phantom insight.** Inventing a quote or sentiment score when Gong was never connected — escalate instead.
- **Coaching as surveillance.** Leading with performance rankings, which kills rep trust in the whole system.
