# Test Contract Guidance

Use this scope for regression tests that protect handler's agent-facing behavior.

## Coverage Priorities

- Add focused tests for behavior changes before broad suite runs.
- Cover both success and failure paths for CLI, MCP, and service flows.
- Assert stable structured-output fields when output contracts are touched.

## Safety And Validation Cases

- Include malformed-input cases for URLs, identifiers, and control-character probes.
- Prefer deterministic assertions on IDs/state transitions over model-text exact matches.
- Ensure terminal-task semantics are covered (no continuation or cancel after completion).

## Execution Expectations

- Run targeted modules first with `uv run pytest tests/<module>.py`.
- Run full validation (`just check`, `just test`) when changes span multiple surfaces.
