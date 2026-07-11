---
name: postman
title: Postman
description: Build, test, or automate API request collections in Postman — environments, variables, assertions, mock servers, or a Newman CI gate.
roles: platform, product
---
# Postman

Postman is where the fleet designs, tests, and documents APIs — collections of requests that double as
an executable test suite. This skill is the ABOS-adapted path to using it well: **connect it as a tool
first, never assume it's wired**, then structure the workspace so it runs headlessly in CI.

## Connect before you build
1. **Find the tool.** `discover_tools` with query `postman`; it exposes as `mcp__postman__*` once the
   founder has connected the workspace. Load what you need with `use_tool` (read a collection, run a
   request, manage an environment).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Postman in
   Settings (MCP server or API key). If the capability can't exist yet, `request_capability`. Never
   invent a response body or a passing test — a phantom result is worse than none.
3. **Least privilege + egress.** Requests hit real third-party endpoints and may carry company data; if
   the target handles sensitive data, `check_compliance` / `list_data_policies` first.

## Structure the workspace so it survives CI
4. **Separate config from requests.** Keep base URLs, tokens, and feature flags in **environments**
   (dev/staging/prod); use collection variables for defaults, environment variables for stage overrides.
   Never hardcode a host or key into a request.
5. **Secrets never touch source control.** Don't commit secrets in an exported environment file — inject
   them at run time. In CI, pass `newman run … --env-var "token=$CI_SECRET"`; the `--env-var` overrides
   the file, so secrets live in the CI vault, not the repo.
6. **Every request asserts.** Write `pm.test` assertions on status, schema, and key fields — a collection
   with no tests is documentation, not a gate. Run it in CI with **Newman**: `--bail` to fail fast,
   `--reporters cli,junit` for artifacts, a data file to parameterize across rows.
7. **Mocks for what isn't built yet.** Use a mock server to unblock frontend/consumer work before the
   real endpoint exists — but gate deploys on the real endpoint, never the mock.

## File the deliverable and record it
8. **Export and file.** Export the collection + environment JSON and `save_file` (category `artifact`)
   with the workspace link in the description — the file store is the durable source, not memory.
9. **Record + hand off.** `write_memory` (type `result`) the run outcome; `record_metric` for pass rate,
   then `dispatch_task` the platform agent to wire Newman into CI, or `report_result`.

## Definition of done
- Postman confirmed connected (or escalated, never faked); sensitive-endpoint egress checked.
- Config in environments, secrets injected at run time, every request has assertions.
- Collection runs green in Newman; export `save_file`d and outcome recorded.

## Common failure modes
- **Secrets in the export.** Committing a token in an environment file leaks it — inject via `--env-var`.
- **Assertion-free collection.** Requests with no `pm.test` pass on any response and gate nothing.
- **Phantom pass.** Claiming tests pass when Postman was never connected — run it or escalate.
