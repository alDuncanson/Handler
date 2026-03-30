# Handler

[![CI](https://github.com/alDuncanson/handler/actions/workflows/ci.yml/badge.svg)](https://github.com/alDuncanson/handler/actions/workflows/ci.yml)
[![A2A Protocol](https://img.shields.io/badge/A2A_Protocol-v0.3.0-blue)](https://a2a-protocol.org/latest/)
[![PyPI version](https://img.shields.io/pypi/v/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI - Status](https://img.shields.io/pypi/status/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI monthly downloads](https://img.shields.io/pypi/dm/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![Pepy total downloads](https://img.shields.io/pepy/dt/a2a-handler?label=total%20downloads)](https://pepy.tech/projects/a2a-handler)
[![GitHub stars](https://img.shields.io/github/stars/alDuncanson/handler)](https://github.com/alDuncanson/handler/stargazers)

![Handler TUI](https://github.com/alDuncanson/Handler/blob/main/assets/handler-tui.png?raw=true)

Handler is an open-source [A2A Protocol](https://github.com/a2aproject/A2A)
client and developer toolkit.

It provides a CLI and TUI for communicating with remote agents, an MCP server
for bridging AI assistants into the A2A ecosystem, a reference server agent
implementation, push notification support, and agent card validation. Whether
you're building agents, integrating with existing ones, or exploring
agent-to-agent communication, Handler gives you the observability and control
you need from your terminal.

## Who is Handler For?

Handler is for developers, researchers, and teams working with AI agents. If
you're building agents that speak A2A, Handler helps you test and debug them. If
you're integrating with existing A2A agents, Handler gives you a fast way to
explore their capabilities. If you want your AI assistant to communicate with
other agents, Handler's MCP server bridges that gap. And if you're just curious
about agent-to-agent communication, Handler is a great place to start.

## Get Started

### Install

Install with [uv](https://github.com/astral-sh/uv):

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

### Run

Or, run from an ephemeral environment:

```bash
# With uv
uvx --from a2a-handler handler

# With pipx
pipx run a2a-handler
```

### Development Environment

A [hermetically sealed](https://zero-to-nix.com/concepts/hermeticity/)
development environment is available with
[Nix](https://zero-to-nix.com/concepts/nix/):

```bash
nix develop
```

This provides Python, uv, and just with all commands ready to use.

For usage documentation, see the
[Handler docs](https://alduncanson.github.io/Handler/).

## Connections (TOML)

Handler supports optional named connections in
`~/.handler/connections.toml` and repository-local `.handler/connections.toml`.

The TUI shows configured connections alongside recently used URLs in a
connection source selector. Auth resolution order is:

1. Auth override entered in the TUI Auth tab.
2. Default auth from the selected connection definition.

Example:

```toml
version = 1

[connections.local]
url = "http://localhost:8000"

[connections.local.auth]
type = "bearer"
env = "HANDLER_LOCAL_TOKEN"

[connections.staging]
url = "https://staging.example.com"

[connections.staging.auth]
type = "api_key"
env = "HANDLER_STAGING_API_KEY"
header = "X-API-Key"

[connections.secure]
url = "https://secure.example.com"

[connections.secure.auth]
type = "mtls"
cert = "/path/to/client.crt"
key = "/path/to/client.key"
ca_cert = "/path/to/ca.crt"  # optional
```

For connection auth, use environment variables where possible. Literal `value`
fallbacks are supported for local development. mTLS connections use file paths
for client certificates instead of environment variables.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
