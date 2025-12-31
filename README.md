# Handler

[![CI](https://github.com/alDuncanson/handler/actions/workflows/ci.yml/badge.svg)](https://github.com/alDuncanson/handler/actions/workflows/ci.yml)
[![A2A Protocol](https://img.shields.io/badge/A2A_Protocol-v0.3.0-blue)](https://a2a-protocol.org/latest/)
[![PyPI version](https://img.shields.io/pypi/v/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI - Status](https://img.shields.io/pypi/status/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI monthly downloads](https://img.shields.io/pypi/dm/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![Pepy total downloads](https://img.shields.io/pepy/dt/a2a-handler?label=total%20downloads)](https://pepy.tech/projects/a2a-handler)
[![GitHub stars](https://img.shields.io/github/stars/alDuncanson/handler)](https://github.com/alDuncanson/handler/stargazers)

**Handler is an open-source [A2A Protocol](https://github.com/a2aproject/A2A) client and developer toolkit.**

![Handler TUI](https://github.com/alDuncanson/Handler/blob/main/assets/handler-tui.png?raw=true)

## What is Handler?

Handler is an enterprise-ready A2A client that provides everything you need to communicate with remote agents, inspect tasks, debug interactions, and operate in the agent-to-agent ecosystem. Whether you're exploring A2A for the first time, developing your own agents, or running agents in production, Handler gives you the observability and control you need from your terminal.

## What's Included

Handler is more than a client. It's a growing collection of A2A infrastructure components:

- **CLI** - Send messages, stream responses, manage sessions, inspect tasks, cancel operations, and validate agent cards from the command line
- **TUI** - A full terminal user interface for conversing with agents, inspecting tasks, and viewing artifacts
- **MCP Server** - Exposes all of Handler's A2A capabilities over the Model Context Protocol, enabling any MCP-compatible host (Claude, Gemini CLI, Cursor, etc.) to send A2A messages and interact with agents
- **Server Agent** - A reference A2A agent implementation powered by Google ADK, LiteLLM, and Ollama for local inference
- **Push Notification Server** - A webhook server for receiving asynchronous push notifications from agents
- **Web Interface** - Serve the TUI as a web application for browser-based access
- **Agent Card Validation** - Validate agent cards from URLs or local files against the A2A protocol specification
- **Session & Credential Management** - Persist conversation context and authentication credentials across sessions for seamless multi-turn interactions

More components are on the way as the A2A ecosystem matures.

## Who is Handler For?

Handler is for developers, researchers, and teams working with AI agents. If you're building agents that speak A2A, Handler helps you test and debug them. If you're integrating with existing A2A agents, Handler gives you a fast way to explore their capabilities. If you want your AI assistant to communicate with other agents, Handler's MCP server bridges that gap. And if you're just curious about agent-to-agent communication, Handler is a great place to start.

## Get Started

Install with [uv](https://github.com/astral-sh/uv):

```bash
uv tool install a2a-handler
```

Or run in an ephemeral environment:

```bash
uvx --from a2a-handler handler
```

For usage documentation, see the [Handler docs](https://alduncanson.github.io/Handler/).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
