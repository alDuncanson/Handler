# Handler Repository Map

Load this reference after `exploring-handler-repository` classifies the request.

## Primary Runtime Areas

1. `src/a2a_handler/service.py`: protocol-facing core abstraction used by CLI, TUI, and MCP.
1. `src/a2a_handler/cli/`: user-facing command entrypoints (`auth`, `card`, `message`, `task`, `session`, `server`, `mcp`).
1. `src/a2a_handler/tui/`: Textual app shell, widget composition, and interaction state.
1. `src/a2a_handler/mcp/server.py`: MCP tool definitions that expose A2A operations to assistants.
1. `src/a2a_handler/server/`: local A2A reference server app, card generation, and agent runtime helpers.
1. `src/a2a_handler/session.py` and `src/a2a_handler/auth.py`: persistence for continuity and credentials.

## Typical Interaction Paths

1. CLI path: command parser -> command module -> `A2AService` -> remote A2A endpoint.
1. TUI path: UI action/event -> component state update -> `A2AService` call -> artifact/log rendering.
1. MCP path: MCP tool call -> validation/normalization -> `A2AService` call -> structured tool result.
1. Local server path: Starlette app -> server agent utilities -> model/provider adapters.

## Fast Orientation Commands

1. `rg --files src/a2a_handler`.
1. `rg --files tests`.
1. `rg "class A2AService|def .*send|def .*task|def .*notification" src/a2a_handler`.

## Exploration Heuristics

1. Start with the narrowest surface the user cares about (CLI, MCP, TUI, or server).
1. Expand outward to shared abstractions only when needed to explain behavior.
1. Prefer file and symbol anchors over long prose when giving implementation guidance.
