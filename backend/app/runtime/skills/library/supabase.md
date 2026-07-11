---
name: supabase
title: Supabase
description: Stand up or query the app's Postgres database, auth, storage, or edge functions in Supabase, or lock down access with Row-Level Security and keys.
roles: platform, product
---
# Supabase

Supabase is the fleet's Postgres backend — database, auth, storage, and edge functions behind one
project. This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never
assume it's wired**, then build least-privilege so a leaked key can't drain the company.

## Connect before you touch the database
1. **Find the tool.** `discover_tools` with query `supabase`; it exposes as `mcp__supabase__*` once the
   founder has connected the project. Load what you need with `use_tool` (run SQL, manage a table,
   invoke a function).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Supabase in
   Settings (MCP server or project keys). If the capability can't exist yet, `request_capability`.
   Never invent a row, table, or query result — a phantom record is worse than none.
3. **Least privilege + egress.** Reading data sends it to a third party and is screened as egress; if a
   table holds user PII, `check_compliance` / `list_data_policies` before pulling it.

## Build it least-privilege and RLS-on
4. **RLS on every public table, always.** Enable Row-Level Security on anything in the `public` schema —
   without a policy an RLS-on table returns nothing, which is the safe default. Dashboard-created tables
   enable it automatically; SQL-created ones do not, so add it yourself.
5. **Never expose the service-role/secret key.** It bypasses RLS and grants full admin — backend only,
   treat it as a secret, never in client code or a repo. Use the publishable/anon key for the browser
   and let RLS do the gating. Supabase auto-revokes secret keys it finds in public repos.
6. **Write policies on trusted claims, not user metadata.** Base policies on `auth.uid()` or app-role
   claims, never on `user_metadata` (the user can edit it). Index every column a policy filters on —
   an unindexed policy column silently tanks query performance.

## File the deliverable and record it
7. **Save schema and outputs.** Export the migration/SQL or query result and `save_file` (category
   `artifact`) with the project ref in the description — the file store is the durable source, not memory.
8. **Record + hand off.** `write_memory` (type `result`) the change and table touched; `record_metric`
   for measurable outcomes, then `dispatch_task` or `report_result`.

## Definition of done
- Supabase confirmed connected (or escalated, never faked); PII egress checked.
- RLS on for every public table; policies use trusted claims and indexed columns.
- Service-role key kept server-side; schema/result `save_file`d and outcome recorded.

## Common failure modes
- **Leaked service-role key.** Shipping the admin key to the client bypasses every policy — backend only.
- **RLS off, or on with no policy.** Off exposes the table; on with no policy locks everyone out silently.
- **Phantom data.** Claiming a table or row exists when Supabase was never connected — escalate instead.
