---
name: deploy-and-release-ops
title: Deploy & Release Ops
description: Ship changes safely with testing, monitoring, and a rollback path so releases don't become incidents.
roles: platform
---
# Deploy & Release Ops

Every deploy is a chance to break production. This playbook ships changes safely — tested, monitored,
and reversible — so releases advance the product instead of causing incidents.

## Workflow
1. **Verify readiness.** Changes tested and reviewed (`list_repo_files`, `read_repo_file`), acceptance
   criteria met (`product-launch-checklist` for user-facing releases). Unverified code doesn't deploy.
2. **Ensure a rollback path.** Before deploying, confirm you can undo it fast if it goes wrong. A deploy
   with no rollback turns a bug into an outage. This is non-negotiable for anything user-facing.
3. **Deploy incrementally where possible.** Prefer staged/canary rollout over big-bang so problems surface
   on a small blast radius. `dispatch_task` / `request_capability` if the deploy capability is limited.
4. **Watch the release.** Monitor error rates and key metrics (`read_metrics`) during and right after
   deploy. The minutes after release are when regressions show — don't deploy and walk away.
5. **Roll back on real signal, fast.** If metrics degrade, roll back first and diagnose after — restoring
   service beats debugging live. `log_ops_event` throughout.
6. **Confirm and record.** Verify the release is healthy against its success metric; `write_memory` (type
   `result`); `log_ops_event`. If it caused harm, run `incident-postmortem`.

## Decision framework — reversibility over speed
Ship in the smallest reversible increments you can, with monitoring on. A fast irreversible deploy that
breaks is far more expensive than a careful staged one. When unsure, roll back and investigate — service first.

## Definition of done
- Changes tested/reviewed; rollback path confirmed before deploy; staged rollout where possible.
- Release monitored against metrics; rollback-ready on regression; health confirmed and recorded.

## Common failure modes
- **No rollback path.** A bug with no undo becomes an outage.
- **Deploy-and-walk-away.** Missing the post-release window where regressions appear.
- **Debugging live instead of rolling back.** Prolonging user harm to satisfy curiosity.
