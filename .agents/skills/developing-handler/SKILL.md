---
name: developing-handler
description: Implements and refactors handler features using the repository's uv and just workflows. Use when adding CLI TUI MCP behavior, updating shared service logic, or preparing scoped code changes.
metadata:
  internal: true
---

# Developing Handler

Builds production-ready changes in `handler` with minimal drift from project standards.

## Use This Skill When

1. Adding or changing CLI commands under `src/a2a_handler/cli`.
1. Updating TUI behavior in `src/a2a_handler/tui`.
1. Extending MCP functionality in `src/a2a_handler/mcp`.
1. Modifying A2A service flows in `src/a2a_handler/service.py`.

## Development Workflow

1. Read `AGENTS.md` and confirm toolchain expectations (`uv`, `just`, Python 3.11+).
1. Inspect the target module and related tests before editing.
1. Prefer small, scoped changes that preserve existing command behavior.
1. Run targeted tests first, then broader checks if interfaces changed.

## Required Commands

1. Install dependencies: `just install`
1. Run targeted tests: `uv run pytest <tests...>`
1. Run quality checks for touched files: `uv run ruff check <paths...>`
1. Run full validation before final handoff when changes are broad: `just check` and `just test`

## Implementation Guardrails

1. Keep type hints complete and explicit.
1. Reuse existing abstractions (`A2AService`, `Output`, session helpers) before adding new layers.
1. Maintain compatibility for existing CLI flags and TUI interactions unless migration is requested.
1. Avoid adding hidden global state without documenting it.

## Done Criteria

1. Feature behavior is implemented and verified with tests.
1. Lint/type checks pass for touched files.
1. User-facing changes include doc or help text updates when needed.
