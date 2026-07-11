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
3. **Onboard it yourself.** You don't need to wait on the founder for a self-serve tool: sign up for the
   service, self-issue an API key/token (or OAuth credential), then register its MCP endpoint with
   `connect_service` (a name, the endpoint URL, and the token). The tools come online for you on the next
   step. The catalog of tool skills is deliberately scoped to services you *can* self-onboard this way.
   Only when you genuinely can't get credentials — the service needs the founder's identity, payment, or a
   login only they have — `request_user_action` for the founder to provide them.
4. **Use least privilege and verify.** Grant the integration only the access it needs, and scope the token
   as tightly as the service allows. Credentials are handled securely (the platform stores them
   envelope-encrypted) — never hardcode or log secrets. Then actually test it end-to-end with `use_tool` /
   a real call — don't assume it works. A silently misconfigured integration fails at the worst moment.
   Every call still passes governance as external data egress, so a sensitive send may need founder sign-off.
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
