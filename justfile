# Handler Development Commands

# Default - show help
default:
    @just --list

# Install dependencies and set up environment
install:
    uv sync

# Run the reference agent server
server host="0.0.0.0" port="8000":
    uv run handler server --host {{host}} --port {{port}}

# Run the Handler TUI
tui:
    uv run handler tui

# Run the TUI in development mode (with Textual devtools support)
tui-dev:
    uv run textual run --dev a2a_handler.tui:HandlerTUI

# Serve the TUI for web access
web:
    uv run textual serve src/handler/tui.py

# Run the Textual console (for devtools)
console:
    uv run textual console

# Fetch an agent card (CLI)
get-card url="http://localhost:8000":
    uv run handler card {{url}}

# Send a message to an agent (CLI)
send url="http://localhost:8000" message="Hello":
    uv run handler send {{url}} "{{message}}"

# Run tests
test:
    uv run pytest

# Run all code quality checks (lint, format, typecheck)
check:
    @echo "Running linter..."
    uv run ruff check .
    @echo "\nChecking formatting..."
    uv run ruff format --check .
    @echo "\nRunning type checker..."
    uv run ty check
    @echo "\n✓ All checks passed!"

# Fix auto-fixable issues (lint & format)
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Show the current version
version:
    uv version

# Bump version (major, minor, or patch)
bump level="patch":
    uv version --bump {{level}}

# Create a git tag for the current version
tag:
    git tag "v$(uv version --short)"

# Tag and push the release to origin
release: tag
    git push origin "v$(uv version --short)"

# Build docs for production
docs-build:
    bun build docs/src/index.html --outdir docs/dist --minify

# Serve docs locally for development
docs-dev:
    bun docs/src/index.html

# Preview production docs build
docs-preview: docs-build
    uv run python -m http.server -d docs/dist 8080
