# Local Agent Assets

This directory contains repository-local agent assets. Keep guidance here focused on building and maintaining local skills.

## Scope

- `SKILL.md` files under `.agents/skills` must remain self-contained and actionable.
- Skill guidance should reference repository commands (`just`, `uv run`) instead of ad-hoc tool invocations.

## Authoring Rules

- Keep skill descriptions concrete about when to use a skill.
- Prefer short workflows with explicit verification steps.
- Avoid references to removed docs trees (`docs/agent`, `docs/src`).

## Coordination

- Put cross-skill defaults in `.agents/skills/AGENTS.md`.
- Keep repository-wide rules in the root `AGENTS.md`; do not duplicate large sections here.
