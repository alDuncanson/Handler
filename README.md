# Handler

[![CI](https://github.com/alDuncanson/handler/actions/workflows/ci.yml/badge.svg)](https://github.com/alDuncanson/handler/actions/workflows/ci.yml)
[![A2A Protocol](https://img.shields.io/badge/A2A_Protocol-v0.3.0-blue)](https://a2a-protocol.org/latest/)
[![PyPI version](https://img.shields.io/pypi/v/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI - Status](https://img.shields.io/pypi/status/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI monthly downloads](https://img.shields.io/pypi/dm/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![Pepy total downloads](https://img.shields.io/pepy/dt/a2a-handler?label=total%20downloads)](https://pepy.tech/projects/a2a-handler)
[![GitHub stars](https://img.shields.io/github/stars/alDuncanson/handler)](https://github.com/alDuncanson/handler/stargazers)

An [A2A](https://github.com/a2aproject/A2A) Protocol client TUI and CLI.

![Handler TUI](https://github.com/alDuncanson/Handler/blob/main/assets/handler-tui.png?raw=true)

## Install

Install with [uv](https://github.com/astral-sh/uv):

```bash
uv tool install a2a-handler
```

Or run Handler in an ephemeral environment:

```bash
uvx --from a2a-handler handler
```

## Use

For a full list of commands and options:

```bash
handler --help
```

### Server Agent

Handler includes a reference implementation of an A2A server agent built with [Google ADK](https://github.com/google/adk-python) and [LiteLLM](https://github.com/BerriAI/litellm), connecting to [Ollama](https://github.com/ollama/ollama) for local inference.

Use any model from [Ollama's library](https://ollama.com/library):

```bash
handler server agent --model llama3.2:1b
```
> Handler will prompt to pull missing models automatically.

Run with authentication:

```bash
handler server agent --auth
```
> Copy the API key from the terminal output.

### Webhook Server

Run Handler's webhook server to receive asynchronous push notifications from A2A server agents:

```bash
handler server push
```

Then send messages with push notifications enabled:

```bash
handler message send http://localhost:8000 "hello" --push-url http://localhost:9000/webhook
```

### Sending Messages

Send a message and get a response:

```bash
handler message send http://localhost:8000 "What can you help me with?"
```

Stream responses in real-time:

```bash
handler message stream http://localhost:8000 "Tell me a story"
```

Continue a conversation using saved session state:

```bash
handler message send http://localhost:8000 "Follow up question" --continue
```

### Authentication

Save credentials for an agent:

```bash
handler auth set http://localhost:8000 --api-key my-secret
handler auth set https://api.example.com --bearer eyJhbG...
```

### TUI

Launch the terminal user interface:

```bash
handler tui
```

### Web

Serve the TUI as a web application:

```bash
handler web
```

### Agent Cards

Fetch an agent's card:

```bash
handler card get http://localhost:8000
```

And validate an agent card from a URL or a file:

```bash
handler card validate http://localhost:8000
handler card validate ./agent-card.json
```

## Upgrade

Upgrade Handler to the latest version from [PyPI](https://pypi.org/project/a2a-handler/):

```bash
uv tool upgrade a2a-handler
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
