---
name: handler
description: Use this umbrella skill for handler setup, MCP operations, validation, and remote agent testing. It routes to focused reference docs through progressive disclosure.
---

## Workflow

1. Confirm request intent and choose one primary competency: `install-setup`, `mcp-server-operations`, `validation-lifecycle`, or `remote-agent-testing`.
1. If the environment is not ready, run the install and verification steps from `references/install-and-setup.md` before deeper checks.
1. For tool usage and local protocol checks, follow `references/mcp-server-operations.md`.
1. For card quality, protocol conformance, and task-safety assertions, follow `references/validation-and-lifecycle.md`.
1. For end-to-end qualification of non-local agents, follow `references/remote-agent-testing.md`.
1. Capture outputs with target URL, command transcript snippets, and explicit pass or fail outcomes.

## Commands

1. Install the public skill pack entrypoint: `npx skills add alDuncanson/handler`.
1. Reinstall or refresh the entrypoint skill: `npx skills add alDuncanson/handler --force`.
1. Verify handler CLI availability: `handler --help`.
1. Install the CLI if missing: `uv tool install a2a-handler`.
1. Run without global install: `uvx --from a2a-handler handler --help`.
1. Run repository checks during local development: `just check` and `just test`.

## Done Criteria

1. The request is completed through the correct competency reference without mixing unrelated workflows.
1. Required MCP, notification, and lifecycle checks are executed when applicable.
1. Results are reproducible and include commands, target agent context, and pass or fail status.
1. Any unresolved issue is clearly attributed to environment, handler implementation, or remote agent behavior.
