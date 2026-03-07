---
name: exploring-handler-repository
description: Provides progressive repository exploration for handler architecture, module flows, and implementation boundaries. Use when asked for architecture walkthroughs, diagrams, or codepath overviews.
metadata:
  internal: true
---

# Exploring Handler Repository

Builds concise, evidence-backed repository tours for humans and agents working on `handler`.

## Use This Skill When

1. A user asks to explore how handler is structured or how major components interact.
1. A user asks for architecture diagrams, runtime flow maps, or onboarding overviews.
1. A user asks for a focused codepath trace across CLI, TUI, MCP, service, and server modules.
1. A user asks for impact analysis before changing handler internals.

## Workflow

1. Classify the request as `architecture-overview`, `runtime-flow-trace`, `module-deep-dive`, or `change-impact-scan`.
1. Load `references/repository-map.md` for high-level boundaries and canonical entrypoints.
1. If diagrams are requested, load `references/diagram-templates.md` and tailor the diagram to the requested scope.
1. Start broad, then progressively disclose only the files and symbols needed for the current question.
1. Anchor explanations to concrete paths and interfaces (`A2AService`, CLI commands, TUI components, MCP server tools, local server agent).
1. Include verification commands users can run locally to confirm the walkthrough.
1. Call out uncertainty explicitly when a flow spans unverified or environment-dependent behavior.

## Commands

1. List core runtime files: `rg --files src/a2a_handler`.
1. List test surfaces: `rg --files tests`.
1. Find primary service and protocol touchpoints: `rg "A2AService|get_agent_card|send_message|get_task" src/a2a_handler`.
1. Find MCP tool implementations: `rg "@mcp.tool|FastMCP|tool" src/a2a_handler/mcp`.
1. Find CLI entrypoints and command wiring: `rg "@click|@command|def .*\(" src/a2a_handler/cli`.
1. Confirm runnable UX surfaces: `just run --help`.
1. Validate walkthrough assumptions after code changes: `just check` and `just test`.

## Done Criteria

1. The requested architecture or flow is explained with concrete file-level references.
1. The output includes at least one diagram or structured flow description when requested.
1. Entry points, boundaries, and key abstractions are clear enough for implementation follow-up.
1. Validation commands are provided so another engineer can reproduce the walkthrough context.
