# Handler

[![CI](https://github.com/alDuncanson/handler/actions/workflows/ci.yml/badge.svg)](https://github.com/alDuncanson/handler/actions/workflows/ci.yml)
[![A2A Protocol](https://img.shields.io/badge/A2A_Protocol-v0.3.0-blue)](https://a2a-protocol.org/latest/)
[![PyPI version](https://img.shields.io/pypi/v/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI - Status](https://img.shields.io/pypi/status/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI monthly downloads](https://img.shields.io/pypi/dm/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![Pepy total downloads](https://img.shields.io/pepy/dt/a2a-handler?label=total%20downloads)](https://pepy.tech/projects/a2a-handler)
[![GitHub stars](https://img.shields.io/github/stars/alDuncanson/handler)](https://github.com/alDuncanson/handler/stargazers)

Handler is an open-source [A2A protocol](https://github.com/a2aproject/A2A)
client for your terminal.

Use it to talk to A2A agents from an interactive TUI, scriptable CLI, or MCP
server. Handler supports reusable server profiles, structured output for
automation, and production auth patterns including bearer tokens, API keys,
mTLS, and OAuth2 client credentials.

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

## Save a server profile

Handler supports named servers in `$XDG_CONFIG_HOME/handler/servers.toml`
(global) and `.handler/servers.toml` (repo-local).

Define a reusable server profile with auth loaded from the environment:

```toml
version = 1

[servers.local]
url = "http://localhost:8000"

[servers.local.auth]
type = "bearer"
env = "HANDLER_LOCAL_TOKEN"
```

Server profiles are especially useful for OAuth-authenticated, gateway-fronted,
or enterprise A2A services where URLs and auth shape should be reused while
secrets stay in environment variables.

## Documentation

- Hosted docs: <https://handler.alduncanson.com>
- Quickstart source: [docs/quickstart.mdx](docs/quickstart.mdx)
- CLI reference source: [docs/reference/cli.mdx](docs/reference/cli.mdx)

## Development

A [hermetic](https://zero-to-nix.com/concepts/hermeticity/) dev environment
is available via [Nix](https://zero-to-nix.com/concepts/nix/):

Enter the development shell:

```bash
nix develop
```

The Mintlify docs source lives in `docs/`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
