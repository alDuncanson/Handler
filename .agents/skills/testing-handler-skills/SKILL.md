---
name: testing-handler-skills
description: Dry-runs handler-maintainer skills and validates workflow readiness with non-mutating checks. Use when asked to preview what a handler skill run would do, such as "dry run a release".
metadata:
  internal: true
---

# Testing Handler Skills

Provides safe rehearsal flows for maintainer-oriented handler skills before executing mutating actions.

## Use This Skill When

1. A user asks to dry run a maintainer workflow before executing it.
1. A user asks for a release preview, including what commands would run and what artifacts would be produced.
1. A user asks to preflight local skill workflows with quick evidence from non-mutating checks.
1. A user wants execution-ready checklists for `developing-handler`, `testing-handler`, or `releasing-handler` tasks.

## Workflow

1. Classify the request as one of: `dry-run-development`, `dry-run-testing`, `dry-run-release`, `dry-run-remote-qualification`, or `dry-run-repository-exploration`.
1. Load `references/dry-run-playbooks.md` for the exact dry-run playbook and expected output shape.
1. Default to `overview` mode: do not execute commands; return ordered steps with prerequisites, gates, and expected outcomes.
1. If the user asks for execution evidence, switch to `preflight` mode and run only non-mutating commands.
1. Never run mutating release actions (`just bump <scope>`, `just release`) in dry-run mode; report them explicitly as `would-run`.
1. If MCP behavior is in scope, include localhost verification order and required lifecycle/notification checks.
1. Record timestamps, branch context, command status (`executed`, `would-run`, `blocked`), and concise pass/fail reasoning.

## Commands

1. Discover local/public skills: `npx skills add alDuncanson/handler --list`.
1. Discover internal skills: `INSTALL_INTERNAL_SKILLS=1 npx skills add alDuncanson/handler --list`.
1. Install this maintainer skill: `INSTALL_INTERNAL_SKILLS=1 npx skills add alDuncanson/handler --skill testing-handler-skills`.
1. Release preflight evidence commands: `just version`, `just check`, and `just test`.
1. Focused preflight test evidence: `uv run pytest tests/<module>.py`.
1. Focused preflight lint evidence: `uv run ruff check <paths...>`.
1. Mutating release actions to preview only: `just bump patch` (or `minor` / `major`) and `just release`.
1. MCP smoke sequence when dry-running MCP changes: `get_agent_card` -> `validate_agent_card` -> `send_message` -> `get_task`.
1. Notification round-trip when dry-running notification changes: `set_task_notification` -> `get_task_notification`.

## Done Criteria

1. The dry-run output clearly separates executed preflight steps from preview-only steps.
1. Blocking prerequisites and failure risks are explicit and reproducible.
1. MCP/lifecycle/notification verification order is included when those surfaces are in scope.
1. Another engineer can convert the dry run into a real execution without guessing missing steps.
