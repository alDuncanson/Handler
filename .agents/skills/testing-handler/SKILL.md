---
name: testing-handler
description: Runs and extends handler test coverage across CLI TUI service and MCP paths. Use when fixing regressions, adding new behavior, or validating agent-facing safety and output contracts.
metadata:
  internal: true
---

# Testing Handler

Validates `handler` behavior with fast feedback loops and explicit regression coverage.

## Use This Skill When

1. A bug fix needs reproducible tests.
1. A new command or flag changes output or validation behavior.
1. MCP tool behavior is modified.
1. Agent-facing safety constraints are added.

## Test Strategy

1. Start with the smallest failing test or add one for the bug.
1. Run only affected tests until behavior is correct.
1. Add negative tests for malformed agent-like input where relevant.
1. Expand to broader suites after targeted tests pass.

## Standard Commands

1. Targeted tests: `uv run pytest tests/<module>.py`
1. Multiple focused modules: `uv run pytest tests/test_cli_message.py tests/test_task.py`
1. Full tests: `just test`
1. Lint and type checks before finalization: `just check`

## Live MCP Verification

Use this when MCP server behavior, task/session semantics, or notification tools change.

1. Start a local agent at `http://localhost:8000`.
1. Run: `get_agent_card` → `validate_agent_card` → `send_message` → `get_task`.
1. Run notification round-trip: `set_task_notification` → `get_task_notification`.
1. Confirm completed tasks are terminal: continuation with `task_id` fails and `cancel_task` fails.
1. Confirm continuity semantics: continue with `context_id` only, and verify `use_session=true` works.

## Coverage Guidelines

1. Cover success and failure paths for new CLI options.
1. Assert machine-readable output structure when output contracts change.
1. Add validation tests for dangerous inputs (`?`, `#`, `%`, control chars, malformed URLs).
1. Keep tests deterministic and avoid external network dependencies.

## Done Criteria

1. New behavior has tests close to the touched module.
1. Existing relevant tests still pass.
1. Assertions are specific enough to catch regressions without brittle snapshots.
