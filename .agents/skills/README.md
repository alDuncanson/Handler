# Handler Local Skills

This repository ships local skills for agent development workflows.

1. `developing-handler`: implementation and refactoring workflow for CLI, TUI, MCP, and service changes.
1. `testing-handler`: targeted and full-suite testing workflow with regression coverage guidance.
1. `releasing-handler`: version bump, validation, and tag/release workflow.

## MCP Smoke Baseline

When MCP behavior changes, run a live localhost smoke pass against `http://localhost:8000` and confirm:

1. Card discovery and validation (`get_agent_card`, `validate_agent_card`).
1. Message and task lifecycle (`send_message`, `get_task`).
1. Notification config round-trip (`set_task_notification`, `get_task_notification`).
1. Terminal-task safety (completed tasks reject continuation and cancellation).
1. Context continuity (`context_id` reuse) and session continuity (`use_session=true`).
