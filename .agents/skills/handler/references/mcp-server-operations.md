# MCP Server Operations

Use this reference for local MCP server behavior and tool-path validation.

## Workflow

1. Ensure a localhost A2A agent is reachable, typically `http://localhost:8000`.
1. Run smoke checks in required order: `get_agent_card` -> `validate_agent_card` -> `send_message` -> `get_task`.
1. If push notifications are in scope, run `set_task_notification` and then `get_task_notification`.
1. Record outputs and classify failures as transport, auth, protocol, or tool-mapping issues.

## Commands

1. `just run`
1. `handler card get --url http://localhost:8000`
1. `handler card validate --url http://localhost:8000`
1. `handler message send --url http://localhost:8000 --message "ping"`
1. `handler task get --url http://localhost:8000 --task-id <task_id>`

## Done Criteria

1. Core MCP smoke checks pass in the required order.
1. Notification round-trip checks pass when exercised.
1. Any failure includes enough detail to reproduce and triage.
