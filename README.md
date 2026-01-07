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

Install with [uv](https://github.com/astral-sh/uv):

```bash
uv tool install a2a-handler
```

Or run in an ephemeral environment:

```bash
uvx --from a2a-handler handler
```

For usage documentation, see the
[Handler docs](https://alduncanson.github.io/Handler/).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
