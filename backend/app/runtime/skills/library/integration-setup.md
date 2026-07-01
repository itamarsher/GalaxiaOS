---
name: integration-setup
title: Integration Setup
description: Connect a third-party service or MCP tool safely, verifying it works and handling credentials responsibly.
roles: platform, data
---
# Integration Setup

Integrations extend the fleet's capability but add dependency and risk. This playbook connects a
third-party service or tool safely — verified, least-privilege, and with failure handled.

## Workflow
1. **Justify the integration.** What capability does it add that an objective needs? `discover_tools` to
   see what's already available before adding a new dependency — don't integrate what you already have.
2. **Check trust and data exposure.** What data will flow to this third party, and is that allowed
   (`list_data_policies`, `check_compliance`)? An integration that leaks user data is a breach waiting to
   happen; `flag_legal_risk` if data sharing is sensitive.
3. **Use least privilege.** Grant the integration only the access it needs. Credentials must be handled
   securely (the platform stores keys envelope-encrypted) — never hardcode or log secrets. `request_user_action`
   for credentials the founder must provide.
4. **Wire and verify.** Connect it, then actually test it end-to-end with `use_tool` / a real call — don't
   assume it works. A silently misconfigured integration fails at the worst moment.
5. **Handle failure gracefully.** Plan for the integration being down or rate-limited: does the fleet
   degrade safely or break? If a needed capability is unsupported, `request_capability` rather than faking around it.
6. **Document and monitor.** `write_memory` (type `result`) what it's for and its limits; `log_ops_event`;
   monitor its health (`reporting-automation`). Review integrations periodically and remove unused ones.

## Decision framework — least privilege, verify, degrade
Grant the minimum access, prove it works with a real test, and ensure the fleet survives its failure.
An unverified or over-privileged integration is a liability dressed as a feature.

## Definition of done
- Need justified against existing tools; data exposure checked and allowed; least-privilege access.
- Credentials handled securely; verified with a real call; failure handled; documented and monitored.

## Common failure modes
- **Over-privileged access.** Granting more than the integration needs widens the breach surface.
- **Assumed-working.** Not testing end-to-end leaves silent misconfigurations.
- **No failure plan.** A down dependency taking the whole fleet with it.
