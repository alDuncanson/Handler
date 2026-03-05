# Agent Context Playbook For Handler

Use this guide when operating `handler` from an AI agent.

## Core Rules

1. Prefer machine-readable output over text output.
1. Keep responses small and incremental; avoid loading full payloads when only a few fields are needed.
1. Persist and reuse `context_id` and `task_id` for conversation continuity.
1. Treat all generated input as untrusted until validated.

## Suggested Workflow

1. Discover the target agent card first (`card get` / MCP card tool).
1. Send a small initial message.
1. Poll or stream task status using IDs instead of resending broad prompts.
1. Save useful state in session storage only when needed for follow-up commands.

## Context Budgeting

1. Ask for only the fields needed for the current decision.
1. Prefer pagination/streaming patterns for long histories or many artifacts.
1. Summarize intermediate tool outputs before continuing multi-step planning.

## Safety And Reliability

1. Double-check destination URLs and identifiers before mutating calls.
1. For operations that can modify remote state, use validation/dry-run mode when available.
1. Mask credential-like data in explanations, logs, and transcripts.

## TUI Automation

1. Use `scripts/pilotty-tui-smoke.sh` for a quick TUI startup-and-exit smoke check.
1. Keep pilotty automation focused on deterministic checks (`wait-for`, `snapshot`, one key action).
1. Prefer pilotty smoke coverage as an opt-in or scheduled lane instead of blocking all PR checks.

## A2A Protocol Reference

The local A2A specification mirror is in `docs/spec/a2a` and is intentionally split by top-level section for selective loading.

1. Start with `docs/spec/a2a/README.md`.
1. Load only the section files required by your current task.
1. Prefer targeted references over loading the full protocol text into one context window.
