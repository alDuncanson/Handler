# Handler Development Commands

# Default - show help
default:
    @just --list

# Install dependencies
install:
    uv sync

# Run handler (defaults to TUI)
run *args="tui":
    uv run handler {{args}}

# Run tests
test:
    uv run pytest

# Run tests with coverage report
coverage:
    uv run pytest --cov --cov-report=term-missing

# Run all code quality checks (lint, format, typecheck)
check:
    @echo "Running linter..."
    uv run ruff check .
    @echo "\nChecking formatting..."
    uv run ruff format --check .
    @echo "\nRunning type checker..."
    uv run ty check
    @echo "\nAll checks passed!"

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
