---
name: confluence
title: Confluence
description: Write or organize documentation — spaces, pages, templates, the page tree, labels, or permissions — in Confluence, the fleet's wiki and knowledge base.
roles: product, ceo
---
# Confluence

Confluence is the fleet's wiki — the durable home for docs, specs, decisions, and process. This skill is
the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, then write
so the page stays findable and true, because a wiki's whole value is trust and stale pages destroy it.

## Connect before you write
1. **Find the tool.** `discover_tools` with query `confluence`; it exposes as `mcp__confluence__*` once the
   founder has connected it. Load what you need with `use_tool` (read/create pages, set labels, permissions).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Confluence in
   Settings (MCP server or API key). Never invent a page link or cite a doc that doesn't exist — a phantom
   reference is worse than a missing one.
3. **Least privilege + egress.** Publishing company knowledge is third-party egress; if a page carries
   sensitive material, `check_compliance` / `list_data_policies` and restrict the space before writing.

## Write so the wiki stays trusted
4. **Space per team or project, nest under clear parents.** One space per domain; within it, nest pages
   under obvious parent pages so the left-sidebar page tree reads like a map, not a pile.
5. **Templates for anything recurring.** Use built-in or custom templates for specs, retros, and decisions so
   structure is predictable and no required section gets missed — search before creating to avoid a duplicate.
6. **Label with a shared vocabulary.** Apply a short, agreed label set so pages are findable across the tree
   regardless of location; use the filter-by-label macro to surface everything on a topic.
7. **Default open, restrict narrowly.** Keep admins few and permissions simple; over-restricting breaks trust
   and makes people stop using the wiki. Restrict only what genuinely must be.

## Keep it clean and record it
8. **Archive on a routine, don't let it rot.** Mark superseded pages, move stale docs to an archive space, and
   flag top-level branches for periodic review so the tree keeps matching reality.
9. **File and record.** `save_file` (category `artifact`) the page link for the durable reference, `write_memory`
   (type `result`) what was documented, then `report_result` or `dispatch_task` the reviewer.

## Definition of done
- Confluence confirmed connected (or escalated, never faked); sensitive pages permissioned and egress-checked.
- Page nested under a clear parent, built from a template, labeled with the shared vocabulary.
- Stale content archived, page link filed and recorded.

## Common failure modes
- **Phantom page.** Citing or linking a doc that doesn't exist because Confluence was never connected — escalate.
- **Stale-doc rot.** Never archiving, so the wiki fills with outdated pages and readers stop trusting it.
- **Permission tangle.** Over-restricting until nobody can find anything and the wiki quietly dies.
