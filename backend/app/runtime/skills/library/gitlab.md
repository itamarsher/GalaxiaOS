---
name: gitlab
title: GitLab
description: Open or review merge requests, wire up CI/CD pipelines, or lock down branches and deploy access in a GitLab project.
roles: platform, product
---
# GitLab

GitLab is where the fleet's code, review, and delivery pipeline live — merge requests, `.gitlab-ci.yml`,
protected branches, and environments. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then operate least-privilege and verify the
pipeline actually shipped what you claim.

## Connect before you touch the repo
1. **Find the tool.** `discover_tools` with query `gitlab`; it exposes as `mcp__gitlab__*` once the
   founder has connected it. Load what you need with `use_tool` (read MRs, trigger a pipeline, manage
   branches).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect GitLab in
   Settings (MCP server or a **project/group access token**, never a personal admin token). If the
   capability can't exist yet, `request_capability`. Never invent an MR link or claim a pipeline passed.
3. **Least privilege + egress.** Scope tokens to the narrowest role and shortest life; pushing code or
   logs sends company data to a third party — `check_compliance` / `list_data_policies` if it's sensitive.

## Operate the merge + pipeline well
4. **MRs are the only path to protected branches.** Protect `main`: no direct push, require approval and
   a green pipeline before merge. Keep MRs small and single-purpose so review is real, not rubber-stamp.
5. **Split the pipeline by trust.** Lint/test jobs run on MR pipelines; **build/deploy jobs with secrets
   run only on protected branches** (`rules: if $CI_COMMIT_REF_PROTECTED`). Mark deploy variables
   *protected* + *masked* so fork/MR pipelines can never read them.
6. **Scope CI tokens and environments.** Restrict `CI_JOB_TOKEN` to the projects it truly needs; define
   real GitLab *environments* (staging → production) so deploys are tracked and rollback is one click.

## Verify, then file it
7. **Verify end-to-end, not off a green check.** A passed pipeline is not a shipped feature — confirm the
   deploy with `get_render_deploy` / `get_render_logs` (or the environment's live URL) before reporting success.
8. **Record + hand off.** `write_memory` (type `result`) the MR link and what merged; `report_bug` or
   `open_issue` for anything the pipeline surfaced; `dispatch_task` follow-up, then `report_result`.

## Definition of done
- GitLab confirmed connected (or escalated, never faked); token scoped least-privilege.
- `main` protected, review + green pipeline required; secrets protected/masked and branch-gated.
- Deploy verified live end-to-end; MR link and outcome recorded and handed off.

## Common failure modes
- **Phantom merge.** Claiming an MR merged or a pipeline passed when GitLab was never connected — escalate.
- **Secrets in MR pipelines.** Unprotected variables leak to fork pipelines that any contributor can trigger.
- **Green-check trust.** Reporting success off a passed job without confirming the environment actually deployed.
