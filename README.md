# Handler

[![CI](https://github.com/alDuncanson/handler/actions/workflows/ci.yml/badge.svg)](https://github.com/alDuncanson/handler/actions/workflows/ci.yml)
[![A2A Protocol](https://img.shields.io/badge/A2A_Protocol-v1.0.0-blue)](https://a2a-protocol.org/latest/)
[![PyPI version](https://img.shields.io/pypi/v/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI - Status](https://img.shields.io/pypi/status/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![Pepy total downloads](https://img.shields.io/pepy/dt/a2a-handler?label=total%20downloads)](https://pepy.tech/projects/a2a-handler)
[![GitHub stars](https://img.shields.io/github/stars/alDuncanson/handler)](https://github.com/alDuncanson/handler/stargazers)

Handler is an open-source [A2A protocol](https://github.com/a2aproject/A2A)
client for software engineers building, testing, and operating agentic systems.
It provides an interactive TUI, a scriptable CLI with structured output, and an
MCP server that lets other agents integrate with A2A services directly. Handler
also supports global and repo-scoped A2A server configuration with bearer,
API key, mTLS, and OAuth2 client credentials auth.

![Handler TUI connected to the built-in Handler Agent, showing the agent card and a completed assistant response](https://raw.githubusercontent.com/alDuncanson/Handler/73915875903b60dad6e4e404aa7ed91b6d94559f/assets/tui.png)

## Install

Install Handler from the [PyPI package](https://pypi.org/project/a2a-handler/) as a `uv` tool:

```bash
uv tool install a2a-handler
```

Or with [pipx](https://pipx.pypa.io/):

```bash
pipx install a2a-handler
```

Or with pip:

```bash
pip install a2a-handler
```

## Quick Start

Open the interactive terminal UI:

```bash
handler tui
```

Inspect an A2A server's agent card:

```bash
handler card get --url http://localhost:8000
```

Send a message from the CLI:

```bash
handler message send --url URL --text "hello"
```

Open the full documentation:

```bash
handler docs
```

## Run Without Installing

Run Handler with `uvx`:

```bash
uvx --from a2a-handler handler
```

Run Handler with `pipx`:

```bash
pipx run a2a-handler
```

## Documentation

Read the documentation at <https://handler.alduncanson.com>.
