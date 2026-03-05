# Agent DX Contract

This document defines the minimum compatibility contract for agent-facing surfaces in `handler`.

## Goals

1. Keep human DX strong for interactive usage.
1. Provide deterministic, machine-readable behavior for agent usage.
1. Reduce hallucination-driven failures with strict validation and explicit guidance.

## Scope

This contract applies to:

1. CLI commands under `src/a2a_handler/cli`.
1. MCP tools in `src/a2a_handler/mcp/server.py`.
1. Agent-facing docs and skill/context packs under `docs/agent` and `docs/spec`.

## Output Guarantees

1. Every user-facing command should support machine-readable output modes (`json` and, when useful, `ndjson`).
1. Structured output should avoid ANSI escapes and locale-dependent formatting.
1. Error responses in structured mode should include stable fields: `code`, `message`, optional `details`, optional `suggestion`.

## Input Hardening Guarantees

1. Validate all external identifiers and URLs before request dispatch.
1. Reject control characters in user/agent supplied identifiers where not explicitly allowed.
1. Reject malformed or suspicious values likely to come from hallucinated command construction.
1. Keep validation shared between CLI and MCP paths when possible.

## Context Discipline Guarantees

1. Prefer concise defaults in agent output paths.
1. Offer explicit filtering/selection controls for large payloads.
1. Document context-window-safe usage patterns in `docs/agent/CONTEXT.md`.

## Safety Guarantees

1. Mutating operations should have a non-destructive planning/validation mode when practical.
1. Sensitive values should be masked in logs and user-visible output unless explicitly requested.

## Compatibility Policy

1. Structured output field removals are considered breaking changes.
1. New fields may be added if existing fields retain semantics.
1. Major output-contract changes require release-note callouts and migration notes.
