---
name: hotjar
title: Hotjar
description: Understand real user behavior on the site — heatmaps, session recordings, funnels, or on-page surveys — when you need evidence of where users struggle.
roles: product, growth
---
# Hotjar

Hotjar shows how real visitors behave — heatmaps, session recordings, funnels, and surveys. This skill
is the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, then
read *actual* behavior data and never invent it — a fabricated heatmap sends the whole fleet the wrong way.

## Connect before you observe
1. **Find the tool.** `discover_tools` with query `hotjar`; it exposes as `mcp__hotjar__*` once the
   founder has connected it. Load what you need with `use_tool` (read a heatmap, list recordings, pull surveys).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Hotjar in
   Settings (MCP server or API key) and confirm the tracking snippet is installed. If it can't exist yet,
   `request_capability`. Never invent heatmap hot-spots, recording counts, or survey results.
3. **Behavior data is PII-adjacent egress.** Recordings and surveys capture visitor behavior — a survey
   that collects responses is data egress. `check_compliance` / `list_data_policies` before setting one live.

## Read behavior, don't imagine it
4. **Triangulate: heatmap → recording → survey.** A heatmap shows *what* (clicks, scroll depth); pull
   recordings on the same page to see *how*; add a survey to learn *why*. One signal alone misleads.
5. **Mind the sample size.** Hotjar samples once traffic exceeds the plan allowance, and low-traffic
   pages give noisy heatmaps. If you see a sampling notice or thin data, say so — don't present a
   partial picture as the full conversion story. Escalate for more volume rather than over-reading it.
6. **Mask PII by default.** Confirm on-page suppression of emails, digits, and payment/health fields, and
   add suppression tags to any element with personal data — masking happens client-side before data ever
   reaches Hotjar. Never disable it to "see more."
7. **Build funnels to quantify drop-off.** Add up to 10 ordered steps and segment with filters to find
   exactly where users fall out — this turns anecdote into a measurable problem worth fixing.

## File the finding and record it
8. **File and record.** Export the finding (annotated heatmap, recording notes, survey summary) and
   `save_file` (category `artifact`) with the Hotjar link; report only real, sourced numbers.
9. **Record + hand off.** `write_memory` (type `learning`) the insight; `record_metric` the measured
   drop-off/conversion; `dispatch_task` product/design to fix, or `report_result`.

## Definition of done
- Hotjar confirmed connected and tracking live (or escalated, never faked); survey egress checked.
- Findings triangulated across signals; sample size acknowledged; PII masking confirmed on.
- Only real data reported; finding filed with the link, insight recorded and handed off.

## Common failure modes
- **Fabricated data.** Inventing heatmap or survey results when Hotjar was never connected or read.
- **Over-reading a tiny sample.** Presenting sampled or low-traffic data as a confident conclusion.
- **Leaking PII.** Recording with masking off, so emails and payment data flow to a third party.
