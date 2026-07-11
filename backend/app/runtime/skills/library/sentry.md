---
name: sentry
title: Sentry
description: Diagnose production errors or performance in Sentry — triage a spiking issue, cut alert noise, wire releases and source maps, or track down a regression.
roles: platform
---
# Sentry

Sentry is where the fleet sees production break — grouped errors, releases, and performance traces. This skill is the ABOS-adapted path to using it well: **connect it as a tool first with least-privilege credentials, never assume it's wired**, then make it signal, not noise, and verify a fix against real events.

## Connect before you triage
1. **Find the tool.** `discover_tools` with query `sentry`; Sentry exposes as `mcp__sentry__*` once connected. Load what you need with `use_tool` (list issues, read an event, resolve or assign).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Sentry in Settings with an **auth token scoped to the specific project**, minimum access. If the capability can't exist yet, `request_capability`. Never invent an issue link or claim an error is resolved — a phantom fix is worse than none.
3. **Least privilege + egress.** Event payloads can contain user data and stack traces; screen with `check_compliance` / `list_data_policies` before exporting them off-platform.

## Make it signal, not noise
4. **Fix grouping at the source.** Trust the default fingerprint first; only add custom fingerprint rules to merge errors sharing one root cause or split a bucket that's masking distinct bugs. Exclude third-party/`node_modules` frames, and include `{{ default }}` to refine rather than replace built-in grouping.
5. **Upload source maps on every release.** Tie the deploy's release version to the SDK and upload source maps at build time — otherwise stack traces are minified and both triage and grouping degrade.
6. **Alert on what's actionable.** Issue alerts for new/regressed issues on critical paths (auth, payments, checkout); metric alerts for aggregate health (error rate, p95). Route to the right owner; delete alerts nobody acts on. For performance, start sampling low (10–30%) and tune.
7. **Triage narrow, then widen.** Work the highest-volume and newest-on-critical-paths issues first; assign an owner, link the fix, and regroup noisy "unique" errors that share a cause instead of resolving them one by one.

## Verify, file, and record
8. **Confirm the fix in events.** Resolve against a release and confirm the issue doesn't recur in new events / regress — don't mark resolved off the code change alone. File the underlying bug with `report_bug` / `open_issue`.
9. **Record and hand off.** `write_memory` (type `result`) the issue URL and root cause; `record_metric` for error-rate movement; `dispatch_task` the fix owner or `report_result`.

## Definition of done
- Sentry connected with a least-privilege, project-scoped token (or escalated, never faked); event-data egress checked.
- Grouping sane; releases + source maps wired; alerts actionable and owned.
- Fix verified against new events; issue link and root cause recorded, bug filed and handed off.

## Common failure modes
- **Phantom fix.** Marking an issue resolved without confirming it stops recurring in real events.
- **Minified blindness.** No source maps or release tagging, so traces are unreadable and grouping is wrong.
- **Alert fatigue.** Noisy, unowned alerts on non-critical paths that train the fleet to ignore Sentry.
