# Handler Diagram Templates

Use these templates after `exploring-handler-repository` identifies the requested flow.

## System Context

```mermaid
flowchart LR
    User[User or Agent] --> Surface[CLI / TUI / MCP]
    Surface --> Service[A2AService]
    Service --> Remote[Remote A2A Agent]
    Surface --> Session[Session + Auth Persistence]
    Surface --> Local[Optional Local A2A Server]
```

## Message Lifecycle

```mermaid
sequenceDiagram
    participant U as User/Caller
    participant S as CLI/TUI/MCP Surface
    participant A as A2AService
    participant R as Remote Agent
    U->>S: send_message
    S->>A: normalize + dispatch
    A->>R: message/send
    R-->>A: task_id + state
    A-->>S: structured response
    U->>S: get_task
    S->>A: fetch task
    A->>R: task/get
    R-->>A: task state/artifacts
    A-->>S: structured task result
```

## Session Continuity

```mermaid
flowchart TD
    Start[Initial send_message] --> Save[Persist context_id/task_id]
    Save --> ContinueContext[Continue with context_id only]
    Save --> ContinueSession[Continue with use_session=true]
    ContinueContext --> Validate[Validate continuity semantics]
    ContinueSession --> Validate
```

## MCP Tool Sequence

```mermaid
flowchart LR
    Card[get_agent_card] --> ValidateCard[validate_agent_card]
    ValidateCard --> Send[send_message]
    Send --> Task[get_task]
    Task --> NotifySet[set_task_notification]
    NotifySet --> NotifyGet[get_task_notification]
```
