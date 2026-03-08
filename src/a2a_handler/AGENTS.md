# Runtime Contract Guidance

This scope covers CLI, TUI, MCP, and shared service/runtime behavior.

## Output Contract

- Preserve machine-readable output behavior (`json`, `ndjson`) when modifying user-facing interfaces.
- Keep structured error envelopes stable with `code`, `message`, and optional `details` / `suggestion`.
- Avoid introducing locale-dependent or ANSI-formatted content into structured outputs.

## Input Hardening

- Validate URLs and external identifiers before dispatching network calls.
- Reject malformed values and control characters where unsupported.
- Reuse shared validation paths between CLI and MCP when practical.

## Task And Session Semantics

- Completed tasks are terminal and must reject continuation by `task_id`.
- Canceling terminal tasks must fail with explicit typed errors.
- Conversation continuation after completion should use `context_id` without terminal `task_id`.
- `use_session=true` should safely reuse persisted session metadata.

## Safety Expectations

- Favor non-destructive validation modes when adding mutating operations.
- Mask secrets and credential-like values in logs and user-visible outputs.
