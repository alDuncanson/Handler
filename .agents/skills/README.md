# Handler Local Skills

This repository ships local skills for agent development workflows.

1. `developing-handler`: implementation and refactoring workflow for CLI, TUI, MCP, and service changes.
1. `testing-handler`: targeted and full-suite testing workflow with regression coverage guidance.
1. `testing-remote-a2a-agents`: remote and enterprise interoperability validation workflow for hosted A2A agents.
1. `releasing-handler`: version bump, validation, and tag/release workflow.

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
