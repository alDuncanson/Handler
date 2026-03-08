# Handler Skill Pack Guidance

Use this file as the default guidance for all local skills in this directory.

## Required Skill Structure

- Include frontmatter with `name` and `description`.
- Use stable section headers: `Workflow`, `Commands`, and `Done Criteria`.
- Keep command examples copy/paste-safe and aligned to repository tooling.

## Validation Expectations

- If a skill changes MCP behavior, include localhost smoke verification in this order: `get_agent_card` -> `validate_agent_card` -> `send_message` -> `get_task`.
- For notification changes, include `set_task_notification` and `get_task_notification` round-trip checks.
- For task lifecycle changes, assert completed tasks reject continuation and cancellation.

## Documentation Policy

- Keep agent-development guidance in `AGENTS.md` files and local skills.
- Do not add or depend on `docs/agent` or `docs/src` paths.
