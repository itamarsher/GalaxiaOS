---
name: sketch
title: Sketch
description: Produce or hand off UI designs, symbol libraries, and design-system assets in Sketch when the design lives (or should live) in a native macOS Sketch document.
roles: design
---
# Sketch

Sketch is the macOS-native design tool where some of the fleet's UI, symbols, and shared libraries
live. This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never
assume it's wired**, then design so the file survives handoff to developers who never touch the Mac app.

## Connect before you design
1. **Find the tool.** `discover_tools` with query `sketch`; Sketch exposes as `mcp__sketch__*` once the
   founder has connected it. Load what you need with `use_tool` (e.g. read a document, export a frame).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Sketch in
   Settings (MCP server or workspace access). If the capability can't exist yet, `request_capability`.
   Never invent a Sketch share link or claim a symbol exists — a phantom design is worse than none.
3. **Least privilege + egress.** Reading/writing Sketch sends company design data to a third party; if a
   document carries anything sensitive, `check_compliance` / `list_data_policies` first.

## Design so it survives handoff
4. **Symbols in a shared Library, not local copies.** Build reusable Symbols and publish them to a
   Library; documents subscribe and get one-click updates (Replace Library is ~15x faster now). Use
   **nested Symbols** for composed components and text/color overrides for variation — never detach.
5. **Color Variables + Text/Layer Styles as tokens.** Define the brand once as Color Variables and
   shared styles; instances stay linked to the system. During handoff these export as CSS or JSON
   tokens, so the design system becomes buildable, not a separate aesthetic.
6. **Frames with Smart Layout / resizing constraints.** Use Frames (nestable, stackable) with Smart
   Layout so components resize and rearrange with content — the Sketch equivalent of Flexbox, which
   maps cleanly to responsive code instead of pixel-pushing.
7. **Hand off via the web Inspector.** Invite developers to inspect on the Canvas for free — no Mac
   needed. Name pages/Frames clearly, mark done frames, and let devs copy CSS, tokens, and exports.

## File the deliverable and record it
8. **Export and file.** Export final frames/assets and `save_file` (category `artifact`, or `brand`
   for design-system assets) with the Sketch link in the description — the file store is the durable,
   shareable source, not the agent's memory.
9. **Record + hand off.** `write_memory` (type `result`) the file link and what shipped; `dispatch_task`
   the platform agent to implement in code, or `report_result`.

## Definition of done
- Sketch confirmed connected (or escalated, never faked); sensitive-data egress checked.
- Symbols from a shared Library, Color Variables/styles as tokens, Smart Layout used; frames named.
- Final assets exported, `save_file`d with the link, outcome recorded and handed off.

## Common failure modes
- **Phantom design.** Claiming a mockup exists when Sketch was never connected — escalate instead.
- **Detached symbols over library instances.** Local copies that can't update once, so the system rots.
- **Handoff with no structure.** Unnamed Frames and no tokens force a re-design at implementation.
