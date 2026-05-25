# Handler

[![CI](https://github.com/alDuncanson/handler/actions/workflows/ci.yml/badge.svg)](https://github.com/alDuncanson/handler/actions/workflows/ci.yml)
[![A2A Protocol](https://img.shields.io/badge/A2A_Protocol-v0.3.0-blue)](https://a2a-protocol.org/latest/)
[![PyPI version](https://img.shields.io/pypi/v/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI - Status](https://img.shields.io/pypi/status/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI monthly downloads](https://img.shields.io/pypi/dm/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![Pepy total downloads](https://img.shields.io/pepy/dt/a2a-handler?label=total%20downloads)](https://pepy.tech/projects/a2a-handler)
[![GitHub stars](https://img.shields.io/github/stars/alDuncanson/handler)](https://github.com/alDuncanson/handler/stargazers)

![Handler TUI](https://github.com/alDuncanson/Handler/blob/main/assets/handler-tui.png?raw=true)

Handler is an open-source [A2A protocol](https://github.com/a2aproject/A2A) client for your terminal.

Use the TUI or CLI to send messages, manage tasks, and inspect agent cards.
An included MCP server lets your AI assistant talk to A2A agents too.

## Install

```bash
uv tool install a2a-handler
```

Or with [pipx](https://pipx.pypa.io/) / pip:

```bash
pipx install a2a-handler   # or: pip install a2a-handler
```

## Quick Start

```bash
handler tui                              # launch the interactive TUI
handler message send URL "hello"         # send a message from the CLI
handler card get URL                     # fetch an agent card
handler mcp                              # start the MCP server
handler server run agent                 # run the bundled embedded agent
handler docs                             # open the hosted documentation
handler update                           # upgrade Handler to the latest release
```

## Run Without Installing

```bash
uvx --from a2a-handler handler           # or: pipx run a2a-handler
```

## Servers

Handler supports named servers in `$XDG_CONFIG_HOME/handler/servers.toml`
(global) and `.handler/servers.toml` (repo-local).

```toml
version = 1

[servers.local]
url = "http://localhost:8000"

[servers.local.auth]
type = "bearer"
env = "HANDLER_LOCAL_TOKEN"
```

See [docs/](docs) for the full auth reference covering bearer, API key, mTLS,
and OAuth2.

## Development

A [hermetic](https://zero-to-nix.com/concepts/hermeticity/) dev environment
is available via [Nix](https://zero-to-nix.com/concepts/nix/):

```bash
nix develop
```

The Mintlify docs source lives in `docs/`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
