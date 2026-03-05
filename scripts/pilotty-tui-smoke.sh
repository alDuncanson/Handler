#!/usr/bin/env bash

set -euo pipefail

SESSION_NAME="handler-smoke"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

cleanup() {
  pilotty kill -s "$SESSION_NAME" >/dev/null 2>&1 || true
  pilotty stop >/dev/null 2>&1 || true
}

trap cleanup EXIT

require_command uv
require_command pilotty

echo "Starting handler TUI smoke session with pilotty"
pilotty spawn --name "$SESSION_NAME" --cwd "$PWD" uv run handler tui >/dev/null

echo "Waiting for TUI welcome message"
pilotty wait-for -s "$SESSION_NAME" "Welcome! Connect to an agent" -t 30000 >/dev/null

echo "Capturing terminal snapshot"
pilotty snapshot -s "$SESSION_NAME" --format text >/dev/null

echo "Exiting TUI via Ctrl+Q"
pilotty key -s "$SESSION_NAME" Ctrl+Q

echo "Waiting for process shutdown"
for _ in $(seq 1 30); do
  if ! pilotty list-sessions | grep -q "$SESSION_NAME"; then
    echo "Smoke test passed"
    exit 0
  fi
  sleep 0.2
done

echo "TUI session did not exit after Ctrl+Q" >&2
exit 1
