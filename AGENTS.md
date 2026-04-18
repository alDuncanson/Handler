- Use conventional commit syntax for commit messages.

## Release Process

When releasing a new version:

1. **Update version** in `pyproject.toml` (semantic versioning: major.minor.patch)
2. **Commit the version bump** with message: `chore: bump version for release`
3. **uv.lock auto-updates** when pyproject.toml changes — stage and commit separately with: `chore: update uv.lock`
4. **Create git tag**: `git tag v{version}` (e.g., `v0.1.19`)
5. **Push both commits and tag**: `git push origin main v{version}`

Current version: Check `pyproject.toml` [project] section for `version =`
Last release: `git tag -l | sort -V | tail -1`
Commits since last release: `git log --oneline {last_tag}..HEAD`
