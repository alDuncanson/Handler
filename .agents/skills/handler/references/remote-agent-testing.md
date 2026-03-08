# Remote Agent Testing

Use this reference for staged interoperability tests against non-local A2A agents.

## Workflow

1. Gather test inputs: agent URL, auth scheme, expected model behavior, and webhook endpoint for notifications.
1. Run unauthenticated discovery checks first to establish baseline connectivity.
1. Configure credentials and rerun message and task flows under authenticated conditions.
1. Execute notification registration and retrieval checks.
1. Run lifecycle assertions for continuation and cancellation edge cases.
1. Summarize results with clear pass or fail status per stage.

## Commands

1. `handler card get --url <agent_url>`
1. `handler card validate --url <agent_url>`
1. `handler auth set --url <agent_url> --bearer-token <token>`
1. `handler message send --url <agent_url> --message "connectivity check"`
1. `handler task get --url <agent_url> --task-id <task_id>`
1. `handler task notification set --url <agent_url> --task-id <task_id> --webhook-url <webhook_url>`
1. `handler task notification get --url <agent_url> --task-id <task_id>`

## Done Criteria

1. Discovery, auth, messaging, task retrieval, and notification checks have explicit outcomes.
1. Failures are localized to protocol, auth, transport, or remote-agent behavior.
1. A rerunnable command sequence is documented for regression testing.
