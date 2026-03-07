# Handler Skill Dry-Run Playbooks

Use this reference only after `testing-handler-skills` is loaded and the request is classified.

## Output Template

1. Include timestamp, branch, and requested dry-run scope.
1. Report mode as `overview` (no commands run) or `preflight` (non-mutating commands run).
1. For each step, include `status` (`executed`, `would-run`, `blocked`) and one concise reason.
1. End with `next-action` instructions that can be executed directly.

## Dry Run: Release

1. Validate readiness with `just version`, `just check`, and `just test` when in `preflight` mode.
1. List version bump command as `would-run`: `just bump patch` (or requested scope).
1. List tagging/publish command as `would-run`: `just release`.
1. Call out release blockers from check/test output before showing go/no-go summary.

## Dry Run: Development Change

1. Identify touched paths and expected behavior changes.
1. List targeted tests as `would-run` or `executed`: `uv run pytest <tests...>`.
1. List lint/type validation as `would-run` or `executed`: `uv run ruff check <paths...>` and `just check` if scope is broad.
1. Provide exit criteria that match the change surface.

## Dry Run: Test Expansion

1. List regression tests to add or adjust.
1. Show the smallest loop first (`uv run pytest tests/<module>.py`) before full suite.
1. Report deterministic-input expectations and anti-flake guardrails.
1. Include final promotion gate: `just test` and `just check`.

## Dry Run: MCP-Sensitive Changes

1. Include localhost smoke sequence in order: `get_agent_card` -> `validate_agent_card` -> `send_message` -> `get_task`.
1. Include notification round-trip: `set_task_notification` -> `get_task_notification`.
1. Include terminal-task safety checks (completed tasks reject continuation and cancellation).
1. Include continuity checks (`context_id` reuse and `use_session=true`).
