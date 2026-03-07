# Remote Agent Qualification

Use this guide when the task track is `remote-agent-qualification`.

## Baseline Sequence

1. Fetch and validate card metadata with `get_agent_card` then `validate_agent_card`.
1. Run a message lifecycle probe with `send_message` then `get_task`, preserving `context_id` and `task_id`.
1. Verify terminal-task safety by confirming completed tasks reject both continuation by `task_id` and cancellation.
1. Verify continuity semantics by continuing with `context_id` only and with `use_session=true`.
1. Verify notification round-trip with `set_task_notification` then `get_task_notification`.

## Failure-Mode Probes

1. Validate malformed IDs return structured client-safe errors.
1. Validate invalid webhook URLs fail via handler-side validation before remote dispatch.
1. Validate authentication failures are explicit and do not leak credentials.
1. Capture timeout and network boundary failures separately from protocol failures.

## Evidence Template

1. Record target URL, environment label, tool version, and timestamp.
1. Record each check as pass or fail with a concise reason.
1. Save structured request and response excerpts with secrets redacted.
1. Classify each failure as `handler validation gap`, `remote agent protocol gap`, or `environment constraint`.
