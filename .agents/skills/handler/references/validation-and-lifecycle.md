# Validation And Lifecycle

Use this reference to verify protocol quality and task-safety semantics.

## Workflow

1. Validate the agent card and inspect errors or warnings before task execution.
1. Confirm completed tasks cannot be continued with `task_id`.
1. Confirm completed tasks cannot be canceled.
1. Verify continuity semantics by reusing `context_id` without terminal `task_id`.
1. Verify session continuity path with `use_session=true` when relevant.

## Commands

1. `handler card validate --url <agent_url>`
1. `handler task get --url <agent_url> --task-id <task_id>`
1. `handler task cancel --url <agent_url> --task-id <completed_task_id>`
1. `handler message send --url <agent_url> --context-id <context_id> --message "follow up"`
1. `handler message send --url <agent_url> --message "continue" --use-session`

## Done Criteria

1. Card validation output is captured and interpreted.
1. Terminal-task safety checks are explicitly verified.
1. Context and session continuity semantics are validated when applicable.
