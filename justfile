# Handler Development Commands

# Default - show help
default:
    @just --list

# Install dependencies
install:
    uv sync

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

# Build docs for production
docs-build:
    bun build docs/src/index.html --outdir docs/dist --minify

# Serve docs locally for development
docs-dev:
    bun docs/src/index.html

# Preview production docs build
docs-preview: docs-build
    uv run python -m http.server -d docs/dist 8080
