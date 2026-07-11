---
name: aws
title: AWS
description: Provision or manage AWS infrastructure — IAM, compute, storage, regions — or set up cost controls, budgets, and tagging on an account.
roles: platform
---
# AWS

AWS is the fleet's cloud substrate — compute, storage, networking, and IAM. It is powerful, metered, and
unforgiving of mistakes. This skill is the ABOS-adapted path to using it well: **connect it as a tool
first, never assume it's wired**, then work least-privilege, tag and budget everything, and never touch
the root account.

## Connect before you provision
1. **Find the tool.** `discover_tools` with query `aws`; it exposes as `mcp__aws__*` once the founder has
   connected it. Load what you need with `use_tool` (read resources, provision, query billing).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect AWS in Settings
   (MCP server or a **scoped IAM role/access key** — never root credentials). If the capability can't exist
   yet, `request_capability`. Never invent an ARN or claim a resource is running.
3. **Least privilege + egress.** Use a role scoped to the exact actions and resources; data landing in S3
   or RDS is egress — `check_compliance` / `list_data_policies` before storing anything sensitive.

## Operate like the Well-Architected Framework
4. **Never use the root account.** Root can't be constrained by IAM policies — no root access keys, MFA on
   it, and use it only for the rare task that requires it. Prefer roles over long-lived keys; rotate what
   exists. Grant every identity the minimum permissions, and lean on Access Analyzer to prune unused ones.
5. **Tag everything, pick regions deliberately.** Tag by owner/service/environment so cost and access are
   attributable (ABAC). Choose a region for latency, data residency, and price — and stay consistent;
   cross-region sprawl silently multiplies cost and complexity.
6. **Cost is real spend — budget it.** Set AWS Budgets with alerts before provisioning. `request_budget`
   for material infrastructure (large instances, managed DBs, data egress) and `request_decision` for
   large/irreversible actions. Use SCPs/instance-type limits to keep sandbox accounts from running away.

## Verify, then file it
7. **Verify it's actually running.** Confirm the resource responds end-to-end (health check, `get_render_logs`
   for the app) before reporting success — a created resource is not a working one.
8. **Record + hand off.** `write_memory` (type `result`) the ARNs/config and monthly cost estimate;
   `record_metric` spend where it matters; `open_issue` for misconfig; `dispatch_task`, then `report_result`.

## Definition of done
- AWS confirmed connected (or escalated, never faked); scoped role/key, root untouched.
- Least-privilege IAM, everything tagged, region deliberate, budget set and material spend approved.
- Resource verified running end-to-end; ARNs, config, and cost recorded and handed off.

## Common failure modes
- **Phantom infra.** Claiming a resource is running when AWS was never connected — escalate instead.
- **Root or wildcard keys.** Long-lived root/`*:*` credentials that turn any leak into a full account takeover.
- **Untagged, unbudgeted spend.** Resources nobody owns quietly running up a metered bill with no alert.
