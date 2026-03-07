# Agent Development Guide

## Guidance Hierarchy

- This root file defines repository-wide defaults.
- Additional `AGENTS.md` files provide progressively disclosed instructions in narrower scopes:
  - `.agents/AGENTS.md` and `.agents/skills/AGENTS.md` for local skill-pack development.
  - `src/a2a_handler/AGENTS.md` for runtime and interface contract expectations.
  - `tests/AGENTS.md` for regression and contract coverage expectations.
  - `docs/AGENTS.md` and `docs/spec/a2a/AGENTS.md` for docs maintenance and protocol mirror usage.
- When guidance overlaps, prefer the most specific (deepest) `AGENTS.md` in the current path.

## Quick Start

```bash
just install  # Install dependencies
just check    # Run lint, format, and typecheck
just test     # Run tests
just run      # Run TUI (default)
just run --help  # Show CLI help
```

Run `just` to see all available commands.

## Environment And Package Management

- This project is managed with `uv`; use `uv` and `uv run` for Python and dependency operations.
- Do not use system `python`, `python3`, `pip`, or `pip3` directly for project tasks.
- Prefer `just` commands first; when running tools manually, use `uv run <tool>`.
- For dependency updates, edit `pyproject.toml` and regenerate the lockfile with `uv lock`.

## Project Structure

```
src/a2a_handler/
├── cli/                 # CLI commands (rich-click)
│   ├── __init__.py      # Main CLI entry point
│   ├── auth.py          # Authentication commands
│   ├── card.py          # Agent card commands
│   ├── mcp.py           # MCP server commands
│   ├── message.py       # Message send/stream commands
│   ├── server.py        # Local server commands
│   ├── session.py       # Session management commands
│   └── task.py          # Task get/cancel/resubscribe commands
├── common/              # Shared utilities
│   ├── config.py        # Configuration
│   ├── logging.py       # Logging setup
│   └── output.py        # Output formatting
├── mcp/                 # MCP server implementation
│   └── server.py        # FastMCP server exposing A2A as tools
├── server/              # Local A2A server agent
│   ├── agent.py         # LLM agent (Google ADK + LiteLLM)
│   ├── app.py           # Starlette A2A server app
│   ├── card.py          # Agent card generation
│   └── ollama.py        # Ollama utilities
├── tui/                 # Textual TUI application
│   ├── app.py           # Main TUI app
│   ├── app.tcss         # TUI styles
│   └── components/      # TUI widgets
│       ├── artifacts.py
│       ├── auth.py
│       ├── card.py
│       ├── contact.py
│       ├── input.py
│       ├── logs.py
│       ├── messages.py
│       └── tasks.py
├── auth.py              # Authentication credentials
├── service.py           # A2AService (core protocol operations)
├── session.py           # Session persistence
├── validation.py        # Agent card validation
└── webhook.py           # Push notification webhook server

tests/                   # pytest test suite
```

## Commands

### Development

```bash
just install    # Install all dependencies
just check      # Run lint + format check + typecheck
just fix        # Auto-fix lint and format issues
just test       # Run pytest
```

### Running

```bash
just run           # Launch TUI
just run tui       # Launch TUI (explicit)
just run web       # Serve TUI as web app
handler --help     # Show CLI help
```

### Release

```bash
just version       # Show current version
just bump patch    # Bump version (major|minor|patch)
just release       # Tag and push release
```

## Commit Messages

- Use **Conventional Commits** for all commit messages.
- Preferred format: `type(scope): short imperative summary` (example: `fix(auth): apply credentials during card discovery`).
- Keep the subject concise and lowercase after the colon.

## Code Style

- **Python 3.11+** with full type hints
- **Formatting**: `ruff format`
- **Linting**: `ruff check`
- **Type Checking**: `ty check`
- **Testing**: pytest with pytest-asyncio
- **No emojis**: Use Unicode symbols (e.g., `\u2600` for sun, `\u2713` for checkmark) instead of emojis in code, docs, comments, and UI

## Key Libraries

- **a2a-sdk**: Official A2A protocol SDK
- **textual**: TUI framework
- **rich-click**: CLI framework
- **httpx**: Async HTTP client
- **google-adk**: Google Agent Development Kit (for server agent)
- **litellm**: LLM provider abstraction
- **mcp**: Model Context Protocol SDK
- **starlette + uvicorn**: ASGI server

## Architecture Notes

- `A2AService` in `service.py` is the core abstraction wrapping the a2a-sdk
- Both CLI and TUI use `A2AService` for protocol operations
- Sessions persist context_id, task_id, and credentials to `~/.handler/sessions.json`
- The MCP server exposes A2A capabilities as tools for AI assistants

## MCP Runtime Verification Notes

- Use a live localhost agent (`http://localhost:8000`) for MCP smoke checks whenever MCP server behavior changes.
- Verify core MCP path in this order: `get_agent_card` → `validate_agent_card` → `send_message` → `get_task`.
- Verify notification path with `set_task_notification` + `get_task_notification` on a known task id.
- Confirm terminal-task semantics: completed tasks cannot be continued with `task_id` and cannot be canceled.
- Confirm context/session continuity semantics: reuse `context_id` (without terminal `task_id`) to continue a conversation and `use_session=true` to use persisted state.

## Skill Maintenance

- At the end of every session, review whether any internal skill (`developing-handler`, `testing-handler`, `releasing-handler`, `testing-handler-skills`, `exploring-handler-repository`) failed, produced incorrect guidance, or would have benefitted from additional or refined instructions.
- If so, update the affected `SKILL.md` (and any associated references under its `references/` directory) before the session ends.
- Fixes include adding missing steps, correcting commands, tightening prerequisites, removing stale guidance, and codifying workarounds discovered during the session.
- Keep changes scoped to the skill that was exercised; do not speculatively edit skills that were not used.
