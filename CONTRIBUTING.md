# Contributing to Handler

## Prerequisites

- **Python 3.11+**
- **[uv](https://github.com/astral-sh/uv)** for dependency management
- **[just](https://github.com/casey/just)** for running commands
- **[Ollama](https://ollama.com/)** (optional, for running the server agent)

## Setup

```bash
git clone https://github.com/alDuncanson/handler.git
cd handler
just install
```

## Development

Run `just` to see all available commands.

### Common Commands

```bash
just check    # Run lint, format check, and typecheck
just fix      # Auto-fix lint and format issues
just test     # Run tests
```

### Running Handler Locally

```bash
uv run handler --help          # Run any CLI command
uv run handler tui             # Launch the TUI
uv run handler server run push # Start the push notification webhook server
```

### Working on the docs

The Mintlify docs source lives in `docs/`.

```bash
npm i -g mint
cd docs
mint dev
```

When the Mintlify GitHub app is connected to this repository, pushes to the
default branch redeploy the docs automatically.

## Code Style

- **Formatting**: `ruff format`
- **Linting**: `ruff check`
- **Type Checking**: `ty check`
- **Testing**: pytest
