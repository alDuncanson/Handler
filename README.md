# Handler

[![CI](https://github.com/alDuncanson/handler/actions/workflows/ci.yml/badge.svg)](https://github.com/alDuncanson/handler/actions/workflows/ci.yml)
[![A2A Protocol](https://img.shields.io/badge/A2A_Protocol-v0.3.0-blue)](https://a2a-protocol.org/latest/)
[![PyPI version](https://img.shields.io/pypi/v/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI - Status](https://img.shields.io/pypi/status/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![Pepy total downloads](https://img.shields.io/pepy/dt/a2a-handler?label=total%20downloads)](https://pepy.tech/projects/a2a-handler)
[![GitHub stars](https://img.shields.io/github/stars/alDuncanson/handler)](https://github.com/alDuncanson/handler/stargazers)

Handler is an open-source [A2A protocol](https://github.com/a2aproject/A2A)
client for your terminal.

Use it to talk to A2A agents from an interactive TUI, scriptable CLI, or MCP
server. Handler supports reusable server profiles, structured output for
automation, and production auth patterns including bearer tokens, API keys,
mTLS, and OAuth2 client credentials.

![Handler TUI connected to the built-in Handler Agent, showing the agent card and a completed assistant response](https://github.com/alDuncanson/Handler/blob/main/assets/handler-tui.png?raw=true)

## Install

Install Handler as a `uv` tool:

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
