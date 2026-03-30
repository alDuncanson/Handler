# Handler Redesign Plan

## Problem

Handler's concepts evolved incrementally — profiles became connections, sessions
track both conversation state and recency, auth lives in three places, and the
CLI/TUI resolve credentials through different paths. The terminology is
inconsistent ("remote", "workspace", "connection", "profile"), the connection
bar has too much chrome, and the CLI uses positional arguments that make
`--help` less useful for both humans and agents.

## Model

Two concepts:

### Server

A configured A2A agent server endpoint. URL + optional auth. This is what you're
connecting to. Can be:

- **Saved** — defined in `servers.toml` (repository-local or global)
- **Recent** — derived from session recency (servers you've connected to that
  aren't in a servers file)
- **Ad-hoc** — a URL typed into the TUI or passed via CLI flag

In the TUI, each tab _is_ a server — either pending (showing the picker) or
active (connected).

```toml
version = 1

[servers.handler_dev]
url = "http://localhost:8000"

[servers.handler_dev.auth]
type = "bearer"
env = "HANDLER_DEV_TOKEN"

[servers.handler_tst]
url = "https://handler-tst.example.com"

[servers.handler_tst.auth]
type = "mtls"
cert = "/path/to/client.crt"
key = "/path/to/client.key"

[servers.handler_prd]
url = "https://handler.example.com"

[servers.handler_prd.auth]
type = "api_key"
env = "HANDLER_PRD_API_KEY"
header = "X-API-Key"
```

### Session

Conversation state for a given server URL. Automatically managed.

- **context_id** — the A2A conversation context
- **task_id** — the last task in the conversation
- **last_used_at** — recency for sorting and deriving "recent" servers

Keyed by server URL, not server name.

---

## Terminology

| Old term   | New term   | Where                     |
| ---------- | ---------- | ------------------------- |
| workspace  | server     | Code, everywhere          |
| remote     | server     | UI tab labels, footer     |
| connection | server     | Config, CLI               |
| profile    | server     | Already gone              |
| agent card | agent card | Stays (A2A protocol term) |
| auth       | auth       | Stays                     |
| session    | session    | Stays                     |

---

## XDG Base Directory Compliance

Move from `~/.handler/` to XDG-compliant paths. Use `platformdirs` for
cross-platform support.

| File            | XDG location                            | Purpose         |
| --------------- | --------------------------------------- | --------------- |
| `servers.toml`  | `$XDG_CONFIG_HOME/handler/servers.toml` | Global servers  |
| `config.toml`   | `$XDG_CONFIG_HOME/handler/config.toml`  | App preferences |
| `sessions.json` | `$XDG_DATA_HOME/handler/sessions.json`  | Session state   |

Repository-local servers stay at `.handler/servers.toml` (relative to git root).

### Credential Store Removal

`credentials.json` is currently used by the CLI and MCP server as a per-URL auth
store. With servers as the single model:

- **Named servers** get auth from `servers.toml`
- **Ad-hoc URLs** get auth from CLI flags or TUI Auth tab
- **`handler auth set`** becomes **`handler server add`**

`credentials.json` is eliminated.

---

## TUI Redesign

### Server Picker

Replace the two-selector (source + target) bar with a single flat selector
listing all servers grouped visually:

```
┌──────────────────────────────────────────────────┐
│ ▼ handler_dev                          CONNECT   │
├──────────────────────────────────────────────────┤
│ Repository                                       │
│   handler_dev        http://localhost:8000        │
│   handler_tst        https://handler-tst.ex...   │
│ Global                                           │
│   handler_prd        https://handler.exampl...   │
│ Recent                                           │
│   https://other-agent.example.com                │
│ ─────────────────────────────────────────────── │
│   Enter URL manually...                          │
└──────────────────────────────────────────────────┘
```

One selector, one button. Tab labels show the server name, then the agent name
after connecting.

### Auth Resolution

No auth mode selector. Resolves automatically:

1. **Auth tab override** — if the user has entered credentials in the Auth tab,
   use those (auto-detected when fields change, already works).
2. **Server default** — auth from `servers.toml`.
3. **None** — no auth.

If server auth is configured but broken (missing env var, missing cert), show a
warning. Do not silently fall back.

### Session Resume

No launch mode selector. Auto-resume by default:

- If a session exists for the server URL, resume automatically.
- **"Start Fresh"** available via command palette (`Ctrl+P` → "Start Fresh").
- Status shows "Resuming session" or "New session".

### Status Row

Collapse the four status badges into one line, use text styles to make them
stand out (bold, underlined, colored, etc):

```
handler_dev · http://localhost:8000 · Bearer (env) · Resuming e66a5ca2...
```

### UI Labels

- Tab: server name → agent name after connecting
- Footer: `Ctrl+B Prev Server`, `Ctrl+T Next Server`, `Ctrl+N New Server`,
  `Ctrl+W Close Server`
- Button: `+ New Server`

### Startup

```sh
# Default: one empty server tab
handler tui

# Pre-connect named servers
handler tui --connect handler_dev
handler tui --connect handler_dev --connect handler_tst

# Quick connect to a URL
handler tui --url http://localhost:8000
```

Future: startup config in `config.toml`:

```toml
[startup]
connect = ["handler_dev", "handler_tst"]
```

---

## CLI Redesign

### Clean Break

Handler is beta software with few users. The entire CLI command surface is being
redesigned for clarity — no backward compatibility shims, no deprecation
warnings, no aliases for old commands. If a command changes, it just changes.
This is the time to get it right.

### CLI Restructure

`handler server` currently runs local servers (`handler server agent`,
`handler server push`). With "server" becoming the primary noun for configured
endpoints, this is restructured:

```
handler server
├── list                          # list configured servers
├── show      NAME                # show server details
├── add       NAME --url URL ...  # add a server
├── remove    NAME                # remove a server
├── validate                      # validate all servers
├── run                           # was: handler server agent
│   ├── agent   [--host] [--port]
│   └── push    [--host] [--port]
```

`handler server run agent` for starting a local server. `handler server` without
a subcommand for managing configured servers.

### Flag-first Design

Convert positional arguments to flags. Every command is fully understandable
from `--help` without memorizing argument order. Order-independent. Agent-
friendly.

**Before:**

```sh
handler message send http://localhost:8000 "Hello agent"
handler task get http://localhost:8000 task-123
handler card get http://localhost:8000
handler auth set http://localhost:8000 --bearer TOKEN
```

**After:**

```sh
handler message send --url http://localhost:8000 --text "Hello agent"
handler message send --server handler_dev --text "Hello agent"
handler task get --url http://localhost:8000 --task task-123
handler card get --server handler_dev
handler server add handler_dev --url http://localhost:8000 --bearer TOKEN
```

Every command accepts `--url` (ad-hoc) or `--server` (named) for agent
targeting. Auth flags (`--bearer`, `--api-key`) override server auth.

### Command Groups

```
handler
├── message
│   ├── send      --server/--url --text [--stream] [--continue] [--bearer/--api-key]
│   └── stream    --server/--url --text [--continue] [--bearer/--api-key]
├── task
│   ├── get       --server/--url --task [--history-length]
│   ├── cancel    --server/--url --task
│   └── resubscribe --server/--url --task
├── card
│   ├── get       --server/--url [--authenticated]
│   └── validate  --server/--url/--file
├── server
│   ├── list
│   ├── show      NAME
│   ├── add       NAME --url URL [--bearer/--api-key/--cert+--key]
│   ├── remove    NAME
│   ├── validate
│   └── run
│       ├── agent   [--host] [--port]
│       └── push    [--host] [--port]
├── session
│   ├── list
│   ├── show      --server/--url
│   └── clear     --server/--url/--all
├── tui           [--connect NAME...] [--url URL]
└── version
```

### Auth Resolution (CLI)

Same precedence as TUI:

1. CLI flags (`--bearer`, `--api-key`) — explicit override
2. Server auth config — from `servers.toml`
3. None

---

## Code Renames

```
src/a2a_handler/
  servers.py               # was connections.py
  auth.py                  # stays
  session.py               # stays
  service.py               # stays
  credential_store.py      # removed
  tui/
    app.py
    app.tcss
    server_tab.py          # was remote_workspace.py
    server_tabs.py         # was workspace_tabs.py
    server_views.py        # was workspace_views.py
    server_types.py        # was workspace_types.py
    server_resolution.py   # was connection_resolution.py
    components/
      ...
  cli/
    server.py              # was connection.py, absorbs auth.py
    ...
```

---

## Migration Path

Each step is independently shippable:

1. **Rename workspace/remote → server** in code, tests, UI labels.
2. **Rename connections.toml → servers.toml**, update config loading.
3. **XDG compliance** — move config/data to XDG paths using `platformdirs`.
4. **Flatten server picker** — merge source + target selectors into one.
5. **Remove auth mode selector** — auto-detect from Auth tab state.
6. **Auto-resume sessions** — remove launch mode selector, add "Start Fresh" to
   command palette.
7. **CLI flag-first** — convert positional args to flags, add `--server`.
8. **CLI restructure** — move `server agent/push` under `server run`, add
   `server add/remove/list/show/validate`.
9. **Remove credential store** — fold `handler auth` into `handler server`.
10. **Add `--connect` startup flag** — pre-connect named servers.
11. **Simplify status row** — collapse badges into single status line.
