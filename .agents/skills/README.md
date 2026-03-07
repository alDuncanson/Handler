# Handler Local Skills

This repository ships local skills for both handler users and handler maintainers.

## Skill Audiences

1. `handler`: public umbrella skill for routing handler usage tasks with progressive disclosure.
1. `testing-remote-a2a-agents`: public specialist skill for validating remote A2A agents with handler MCP and CLI flows.
1. `developing-handler`: maintainer skill for implementing and refactoring handler itself (`metadata.internal: true`).
1. `testing-handler`: maintainer skill for handler repo regression and contract testing (`metadata.internal: true`).
1. `releasing-handler`: maintainer skill for versioning and release operations (`metadata.internal: true`).

## Installation Profiles

1. Install the public umbrella skill only (recommended): `npx skills add alDuncanson/handler --skill handler`.
1. Install the public specialist remote-testing skill directly: `npx skills add alDuncanson/handler --skill testing-remote-a2a-agents`.
1. Preview what is publicly installable without internal skills: `npx skills add alDuncanson/handler --list`.
1. Include internal maintainer skills in discovery: `INSTALL_INTERNAL_SKILLS=1 npx skills add alDuncanson/handler --list`.
1. Install all skills, including internal maintainer skills: `INSTALL_INTERNAL_SKILLS=1 npx skills add alDuncanson/handler --skill '*'`.
1. Target a specific agent explicitly when needed: `npx skills add alDuncanson/handler --skill handler --agent amp`.

## Agent-Agnostic Guidance

1. Keep all skills in `.agents/skills` for compatibility with Amp and other agents that read this path.
1. Use `metadata.internal: true` for maintainer-only skills so Vercel Skills users do not install them by default.
1. For ecosystems that do not honor `metadata.internal`, use explicit `--skill` selection to install only public skills.

## MCP Smoke Baseline

When MCP behavior changes, run a live localhost smoke pass against `http://localhost:8000` and confirm:

1. Card discovery and validation (`get_agent_card`, `validate_agent_card`).
1. Message and task lifecycle (`send_message`, `get_task`).
1. Notification config round-trip (`set_task_notification`, `get_task_notification`).
1. Terminal-task safety (completed tasks reject continuation and cancellation).
1. Context continuity (`context_id` reuse) and session continuity (`use_session=true`).

## Remote Qualification Notes

1. The `testing-remote-a2a-agents` skill is handler-specific and should be run with handler MCP tools first, then CLI fallbacks if needed.
1. Avoid brittle assertions on exact model text during lifecycle checks; assert IDs and state transitions instead.
1. Invalid webhook probes should fail through handler validation (`invalid_webhook_url`) before remote dispatch.
