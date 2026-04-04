"""Repository-local workspace server management for the TUI."""

from __future__ import annotations

import re
from importlib import import_module
from pathlib import Path
from typing import cast

_TOML_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _server_cli_helpers():
    server_module = import_module("a2a_handler.cli.server")
    return (
        server_module._read_toml,
        server_module._resolve_servers_path,
        server_module._write_servers_toml,
    )


def _read_workspace_servers() -> tuple[Path, dict[str, object], dict[str, object]]:
    read_toml, resolve_servers_path, _ = _server_cli_helpers()
    path = resolve_servers_path(use_repository=True)
    if not path.exists():
        raise FileNotFoundError(f"No workspace server file found at {path}")

    data = read_toml(path)
    raw_servers = data.get("servers")
    if not isinstance(raw_servers, dict):
        raise KeyError(f"No workspace servers found in {path}")

    return path, data, cast(dict[str, object], raw_servers)


def _validate_workspace_server_name(name: str) -> None:
    if not name:
        raise ValueError("Workspace server names cannot be empty")
    if not _TOML_KEY_RE.match(name):
        raise ValueError(
            "Workspace server names may only contain letters, numbers, hyphens, and underscores"
        )


def rename_workspace_server(current_name: str, new_name: str) -> Path:
    """Rename a repository-local workspace server definition."""
    _validate_workspace_server_name(new_name)
    _, _, write_servers_toml = _server_cli_helpers()
    path, data, servers = _read_workspace_servers()

    if current_name not in servers:
        raise KeyError(f"Workspace server '{current_name}' was not found")
    if new_name != current_name and new_name in servers:
        raise ValueError(f"Workspace server '{new_name}' already exists")
    if new_name == current_name:
        return path

    servers[new_name] = servers.pop(current_name)
    data["servers"] = servers
    write_servers_toml(path, data)
    return path


def remove_workspace_server(name: str) -> Path:
    """Remove a repository-local workspace server definition."""
    _, _, write_servers_toml = _server_cli_helpers()
    path, data, servers = _read_workspace_servers()
    if name not in servers:
        raise KeyError(f"Workspace server '{name}' was not found")

    del servers[name]
    data["servers"] = servers
    write_servers_toml(path, data)
    return path
