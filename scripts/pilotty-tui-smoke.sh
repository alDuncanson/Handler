#!/usr/bin/env bash

set -euo pipefail

SESSION_NAME="handler-smoke"
PILOTTY_CMD=("pilotty")

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

cleanup() {
  "${PILOTTY_CMD[@]}" kill -s "$SESSION_NAME" >/dev/null 2>&1 || true
  "${PILOTTY_CMD[@]}" stop >/dev/null 2>&1 || true
}

trap cleanup EXIT

require_command uv
if ! command -v pilotty >/dev/null 2>&1; then
  if command -v npx >/dev/null 2>&1; then
    PILOTTY_CMD=("npx" "-y" "pilotty")
  else
    echo "Missing required command: pilotty (or npx fallback)" >&2
    exit 1
  fi
fi

echo "Starting handler TUI smoke session with pilotty"
"${PILOTTY_CMD[@]}" spawn --name "$SESSION_NAME" --cwd "$PWD" uv run handler tui >/dev/null

echo "Waiting for TUI welcome message"
"${PILOTTY_CMD[@]}" wait-for -s "$SESSION_NAME" "Welcome! Connect to an agent" -t 30000 >/dev/null

echo "Capturing terminal snapshot"
"${PILOTTY_CMD[@]}" snapshot -s "$SESSION_NAME" --format text >/dev/null

echo "Exiting TUI via Ctrl+Q"
"${PILOTTY_CMD[@]}" key -s "$SESSION_NAME" Ctrl+Q

echo "Waiting for process shutdown"
for _ in $(seq 1 30); do
  if ! "${PILOTTY_CMD[@]}" list-sessions | grep -q "$SESSION_NAME"; then
    echo "Smoke test passed"
    exit 0
  fi
  sleep 0.2
done

echo "TUI session did not exit after Ctrl+Q" >&2
exit 1
