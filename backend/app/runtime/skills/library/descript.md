---
name: descript
title: Descript
description: Edit a podcast, screen recording, or marketing video by its transcript in Descript — clean up filler, fix audio, and cut repurposable clips.
roles: growth, design
---
# Descript

Descript edits audio and video by editing the *transcript* — the fleet's fast path to clean podcasts,
demos, and social clips. This skill is the ABOS-adapted path to using it well: **connect it as a tool
first, never assume it's wired**, then edit for clarity without crossing the AI-voice consent line.

## Connect before you edit
1. **Find the tool.** `discover_tools` with query `descript`; it exposes as `mcp__descript__*` once the
   founder has connected it. Load what you need with `use_tool` (create a project, read a transcript, export).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Descript in
   Settings (MCP server or account). If the capability can't exist yet, `request_capability`.
   Never invent an export link or claim a clip exists — a phantom edit is worse than none.
3. **Least privilege + egress.** Uploading raw recordings sends company/voice data to a third party; if
   the source is sensitive, `check_compliance` / `list_data_policies` first.

## Edit for clarity, not artifice
4. **Correct the transcript, then cut.** Auto-transcription is fast but imperfect — fix names, terms,
   and spellings first (click a word to hear it), because every downstream edit rides on the transcript.
5. **Remove filler selectively.** Detect and strip "um/uh/like," but don't nuke every one — over-cutting
   sounds robotic. Keep "avoid harsh cuts" on so removals don't clip into neighboring words.
6. **Studio Sound for audio, sparingly.** Apply Studio Sound to clean noise and even out levels; it's a
   polish pass, not a fix for a bad recording.
7. **Overdub is a consent line — mind it.** Overdub (AI voice) is for tiny corrections in a properly
   consented, trained voice only. Never synthesize someone's voice without consent or generate full
   speech passed off as real — that's a compliance and trust risk; `flag_legal_risk` if unsure.

## Repurpose, file, and record it
8. **Cut clips from the long form.** Pull short, captioned highlight clips from the master recording for
   social/growth — repurposing is where one recording becomes a week of content. Publishing/sharing the
   output is gated external comms (indexed, may need sign-off); route through the gate.
9. **File and record.** `save_file` (category `artifact`) exports and clip links; `write_memory`
   (type `result`) what was produced; `record_metric` real clip performance if tracked; `dispatch_task`
   distribution, or `report_result`.

## Definition of done
- Descript confirmed connected (or escalated, never faked); source egress checked.
- Transcript corrected first; filler trimmed selectively; Studio Sound as polish; Overdub only with consent.
- Repurposable clips cut and filed; any publishing passed the comms gate; outcome recorded.

## Common failure modes
- **Phantom edit.** Claiming a clip exists when Descript was never connected — escalate instead.
- **Overdub without consent.** Synthesizing a voice or faking speech — a legal and trust breach.
- **Transcript rot.** Cutting before fixing errors, so every edit compounds a garbled base.
