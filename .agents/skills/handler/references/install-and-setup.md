# Install And Setup

Use this reference when handler is not installed or the local environment needs initialization.

## Workflow

1. Verify prerequisites are available: `uv --version`, `just --version`, and network access to the target agent.
1. Check whether handler is already installed: `handler --help`.
1. If missing, install with `uv tool install a2a-handler`.
1. Use zero-install fallback when global install is not allowed: `uvx --from a2a-handler handler --help`.
1. Confirm the local repository workflow still passes: `just check` and `just test`.

## Commands

1. `uv --version`
1. `just --version`
1. `handler --help`
1. `uv tool install a2a-handler`
1. `uvx --from a2a-handler handler --help`
1. `just check`
1. `just test`

## Done Criteria

1. Handler commands can run in the current environment.
1. The user has at least one verified execution path (`handler` or `uvx`).
1. Baseline repository checks pass or failures are captured with actionable notes.
