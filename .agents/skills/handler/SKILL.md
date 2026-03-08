---
name: handler
description: Routes handler usage work with progressive disclosure for remote A2A qualification and handler CLI or MCP operations. Use when asked to use handler tools, validate remote agents, or run protocol, lifecycle, and notification checks.
---

# Handler

## Use This Skill When

1. A user asks to use handler tools but does not know which handler workflow to run.
1. A user wants one installable skill that can cover remote-agent testing with progressive disclosure.
1. A user asks for handler protocol checks, task lifecycle checks, or notification verification.
1. A user asks for reproducible qualification evidence for a remote A2A endpoint.

## Workflow

1. Classify the request as one of three tracks: `remote-agent-qualification`, `handler-tool-usage`, or `interoperability-triage`.
1. Bootstrap `handler` CLI availability before protocol checks: verify `handler --help`; if unavailable, install with `uv tool install a2a-handler` (or `pipx install a2a-handler`) and continue.
1. If global installation is not possible, use ephemeral execution with `uvx --from a2a-handler handler <subcommand...>` for zero-friction command coverage.
1. For `remote-agent-qualification`, load `references/remote-agent-qualification.md` and run the staged baseline and failure-mode checks.
1. For deeper remote-agent validation workflows, prefer loading `testing-remote-a2a-agents` if available.
1. For `handler-tool-usage`, provide the shortest command path first, then execute checks in increasing scope.
1. For ambiguous requests, ask one short clarification before executing commands.
1. Record outputs as reproducible evidence with timestamps, target URL or branch context, and explicit pass or fail status.

## Commands

1. Install this umbrella skill: `npx skills add alDuncanson/handler --skill handler`.
1. Install only public remote-agent specialization directly: `npx skills add alDuncanson/handler --skill testing-remote-a2a-agents`.
1. Verify local CLI availability: `handler --help`.
1. Install handler CLI when missing: `uv tool install a2a-handler`.
1. Alternative install path: `pipx install a2a-handler`.
1. Zero-install fallback for one-off usage: `uvx --from a2a-handler handler --help`.
1. Preview publicly installable skills: `npx skills add alDuncanson/handler --list`.
1. Target a specific agent explicitly when needed: `npx skills add alDuncanson/handler --skill handler --agent amp`.
1. Run MCP smoke baseline sequence against localhost when MCP behavior changes: `get_agent_card` -> `validate_agent_card` -> `send_message` -> `get_task`.
1. Run notification round-trip checks when notification behavior changes: `set_task_notification` -> `get_task_notification`.
1. Verify terminal-task safety: completed tasks reject continuation by `task_id` and reject cancellation.
1. Verify continuity semantics: continue with `context_id` only and confirm `use_session=true` continuity.

## Done Criteria

1. The request is routed to the correct public handler workflow and executed end-to-end.
1. Required MCP, lifecycle, and notification checks are completed when applicable.
1. Results are reproducible and include enough context for another engineer to rerun.
1. Any gaps are classified clearly as handler behavior, remote agent behavior, or environment constraint.
