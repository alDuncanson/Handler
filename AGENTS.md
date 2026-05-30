- Use conventional commit syntax for commit messages.

## Development Workflow

- Use `gh` for GitHub operations such as checking CI status, viewing workflow logs, and opening PRs.
- Before committing, run local CI/checks relevant to the change. Prefer the same commands CI uses when practical:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run ty check`
  - `uv run pytest`
- Use `ruff` for both linting and formatting Python code:
  - `uv run ruff check ...`
  - `uv run ruff format ...`
- Use `ty` for type checking when Python code changes.
- Use `act` with Docker for local GitHub Actions validation when debugging or validating workflow failures. Ensure Docker is running, then use commands such as:
  - `act -l`
  - `act pull_request -j check`
  - `act pull_request -j check --dryrun`
- Only open a PR after the work has been reviewed together with the user.
- When opening a PR with `gh`, write a thorough summary of the diff, including important behavior changes, cleanup/refactors, and verification performed.

## Release Process

When releasing a new version:

1. **Update version** in `pyproject.toml` (semantic versioning: major.minor.patch)
2. **Refresh `uv.lock`** after the version change (for example, run `uv lock`)
3. **Commit the version and lockfile together** with message: `chore: bump version for release`
4. **Create git tag**: `git tag v{version}` (e.g., `v0.1.19`)
5. **Push the commit and tag**: `git push origin main v{version}`

Current version: Check `pyproject.toml` [project] section for `version =`
Last release: `git tag -l | sort -V | tail -1`
Commits since last release: `git log --oneline {last_tag}..HEAD`
