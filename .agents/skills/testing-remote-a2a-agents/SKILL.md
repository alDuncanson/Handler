---
name: testing-remote-a2a-agents
description: Validates remote A2A agents with handler MCP tools using staged interoperability, auth, task lifecycle, and push notification checks.
---

# Testing Remote A2A Agents

Runs pragmatic, reproducible qualification checks against non-local A2A agents using `handler`.

## Handler Usage Surface

1. Primary path: use handler MCP tools (`get_agent_card`, `validate_agent_card`, `send_message`, `get_task`, `cancel_task`, `set_task_notification`, `get_task_notification`).
1. Preserve `context_id` and `task_id` from each response for later lifecycle checks.
1. Use `use_session=true` only after at least one successful `send_message` call has persisted session state.
1. CLI fallback for humans: use `handler card get`, `handler card validate`, `handler message send`, `handler task get`, `handler task cancel`, and `handler task notification set/get`.

## Use This Skill When

1. Testing a hosted or enterprise-network A2A agent endpoint.
1. Validating auth/session/task semantics before rollout.
1. Investigating remote interoperability issues that do not appear in localhost tests.
1. Producing evidence for security, platform, or vendor review.

## Preconditions

1. Bootstrap `handler` CLI availability before testing: run `handler --help`; if unavailable, install with `uv tool install a2a-handler` (or `pipx install a2a-handler`).
1. If global installation is blocked, run CLI checks with `uvx --from a2a-handler handler <subcommand...>`.
1. Confirm approved target endpoint(s), test credentials, and environment scope (dev, stage, prod-like).
1. Ensure secrets are provided via secure channels and never echoed in logs or transcripts.
1. Prefer machine-readable output (`--output json` in CLI paths) for evidence collection.
1. Start with non-destructive operations and expand only after baseline checks pass.

## Remote Qualification Workflow

1. Endpoint and identity baseline: verify URL format, fetch card (`get_agent_card`), then run `validate_agent_card`.
1. Auth handshake baseline: verify unauthenticated behavior, then repeat with bearer/API key credentials and confirm expected access transitions. Record whether the endpoint is `auth-open` (dev/local) or `auth-enforced`.
1. Core lifecycle baseline: run `send_message` then `get_task` and capture `context_id`, `task_id`, and `state` transitions. Do not require exact model text; assert lifecycle fields and terminal state instead.
1. Terminal-task safety: confirm completed tasks reject continuation by `task_id` and reject cancel.
1. Continuity semantics: continue with `context_id` only and verify session continuity using `use_session=true`.
1. Push path baseline: run `set_task_notification` and `get_task_notification`; validate token handling and callback URL behavior.
1. Failure-mode probes: capture behavior for malformed IDs, invalid webhook URLs, timeout conditions, and auth failures.

## Expected Handler Behaviors

1. Completed tasks are terminal: continuing with terminal `task_id` and canceling completed tasks should fail with explicit errors.
1. Invalid webhook URLs should be rejected by handler-facing surfaces with validation errors (for example `invalid_webhook_url` in structured error data).
1. Notification tokens must be masked/truncated in returned payloads.
1. Session continuity should reuse the latest persisted `context_id` when `use_session=true`.

## Enterprise-Focused Checks

1. Confirm TLS trust behavior from the execution environment and note any certificate-chain constraints.
1. Record latency-sensitive operations and timeout behavior for remote links.
1. Verify proxy/firewall assumptions if webhook callbacks traverse network boundaries.
1. Confirm sensitive values are masked in logs, terminal output, and saved artifacts.
1. Validate rate-limit or throttling responses when present (status, error envelope, retry guidance).

## Evidence Capture

1. Record target URL, timestamp, environment label, and tool version.
1. Save structured request/response excerpts for each phase with secrets redacted.
1. Track pass/fail per check with exact failure reason and reproduction command/tool call.
1. Separate protocol failures from environment failures (network, auth policy, TLS, proxy).
1. When a failure occurs, classify it as one of: `handler validation gap`, `remote agent protocol gap`, or `environment constraint`.

## Done Criteria

1. Baseline remote card, auth, lifecycle, terminal-task, continuity, and notification checks are completed.
1. Results are reproducible and include enough detail for another engineer to rerun.
1. Risks and gaps are explicitly documented with recommended next actions.
