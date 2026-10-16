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
API key, HTTP Basic, mTLS, OAuth2 client credentials, and OpenID Connect auth.

![Handler TUI connected to an A2A agent, showing the agent card and a completed assistant response](https://raw.githubusercontent.com/alDuncanson/Handler/73915875903b60dad6e4e404aa7ed91b6d94559f/assets/tui.png)

## Features

- Streams replies as they arrive, in the TUI and the CLI, and can stop a
  running task or answer an agent that pauses for input
- Sends text, files (inline or by URL), and structured data, and shows the
  file and data parts agents send back
- Lists, inspects, cancels, and resubscribes to tasks, and manages push
  notification configs with a bundled local webhook receiver
- Speaks JSON-RPC and HTTP+JSON out of the box, gRPC with the `grpc` extra,
  and lets the agent card pick the transport
- Requests A2A extensions and fetches the extended card an agent offers to
  authenticated clients
- Keeps credentials on the origin you configured, never on a host an agent
  card happens to name

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

Stream the reply, with a file attached:

```bash
handler message stream --url URL --text "Review this" --file ./report.pdf
```

List the agent's tasks:

```bash
handler task list --url URL
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
