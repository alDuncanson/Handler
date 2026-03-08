---
name: releasing-handler
description: Prepares and verifies handler releases using version bump, checks, and tagging workflows. Use when cutting patch minor major releases or validating release readiness.
metadata:
  internal: true
---

## Release Workflow

1. Ensure branch is up to date and intended changes are committed.
1. Run full quality and test gates.
1. Bump the version according to release scope.
1. Create and push the release tag.

## Standard Commands

1. Show current version: `just version`
1. Run checks: `just check`
1. Run tests: `just test`
1. Bump version: `just bump patch` (or `minor` / `major`)
1. Create and push release tag: `just release`

## Guardrails

1. Do not skip `just check` and `just test` for release branches.
1. Keep commit messages in conventional commit format.
1. Confirm release notes and changelog context are accurate before publishing.

## Done Criteria

1. Version is bumped correctly.
1. Release tag exists and is pushed.
1. CI is green for the release commit/tag.
