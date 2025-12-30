# Agent Development Guide

## Quick Start

```bash
just install  # Install dependencies
just check    # Run lint, format, and typecheck
just test     # Run tests
```

Run `just` to see all available commands.

## Project Structure

```
src/a2a_handler/
├── cli.py           # CLI entry point
├── client.py        # A2A protocol client
├── validation.py    # Agent card validation
├── server.py        # A2A server agent
├── tui.py           # TUI application
├── common/          # Shared utilities
└── components/      # TUI components
```

## Code Style

- **Python 3.11+** with full type hints
- **Formatting**: `ruff format`
- **Linting**: `ruff check`
- **Type Checking**: `ty check`
- **Testing**: pytest with pytest-asyncio
- **No emojis**: Use Unicode symbols (e.g., `\u2600` for sun, `\u2713` for checkmark) instead of emojis in code, docs, comments, and UI
