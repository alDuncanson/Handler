---
name: handler
description: Routes handler-related work with progressive disclosure for remote A2A qualification and handler repository maintenance. Use when asked to use handler CLI or MCP tools, validate remote agents, or run handler-specific workflows.
---

# Handler

Provides a single entrypoint for handler workflows while keeping maintainer paths optional.

## Use This Skill When

1. A user asks to use handler tools but does not know which handler workflow to run.
1. A user wants one installable skill that can cover remote-agent testing and future handler workflows.
1. A user asks for handler protocol checks, task lifecycle checks, or notification verification.
1. A user asks for handler repository implementation, testing, or release workflows.

## Workflow

1. Classify the request as one of four tracks: `remote-agent-qualification`, `handler-development`, `handler-testing`, or `handler-release`.
1. For `remote-agent-qualification`, load `references/remote-agent-qualification.md` and run the staged baseline and failure-mode checks.
1. For `handler-development`, `handler-testing`, or `handler-release`, prefer loading `developing-handler`, `testing-handler`, or `releasing-handler` if those skills are available.
1. If internal maintainer skills are not installed, use the fallback commands in this skill and state that internal skills can be enabled with `INSTALL_INTERNAL_SKILLS=1` during installation.
1. For ambiguous requests, ask one short clarification before executing commands.
1. Record outputs as reproducible evidence with timestamps, target URL or branch context, and explicit pass or fail status.

## Commands

1. Install this umbrella skill: `npx skills add alDuncanson/handler --skill handler`.
1. Install only public remote-agent specialization directly: `npx skills add alDuncanson/handler --skill testing-remote-a2a-agents`.
1. Discover internal maintainer skills during install: `INSTALL_INTERNAL_SKILLS=1 npx skills add alDuncanson/handler --list`.
1. Install internal maintainer skills when needed: `INSTALL_INTERNAL_SKILLS=1 npx skills add alDuncanson/handler --skill developing-handler --skill testing-handler --skill releasing-handler`.
1. Fallback maintainer development loop when internal skills are unavailable: `just install`, `uv run pytest <tests...>`, `uv run ruff check <paths...>`, `just check`, and `just test`.
1. Fallback release loop when internal skills are unavailable: `just version`, `just check`, `just test`, `just bump patch`, and `just release`.
1. Run MCP smoke baseline sequence against localhost when MCP behavior changes: `get_agent_card` -> `validate_agent_card` -> `send_message` -> `get_task`.
1. Run notification round-trip checks when notification behavior changes: `set_task_notification` -> `get_task_notification`.

## Done Criteria

1. The request is routed to the correct handler workflow and executed end-to-end.
1. Required MCP, lifecycle, and notification checks are completed when applicable.
1. Results are reproducible and include enough context for another engineer to rerun.
1. Any gaps are classified clearly as handler behavior, remote agent behavior, or environment constraint.
