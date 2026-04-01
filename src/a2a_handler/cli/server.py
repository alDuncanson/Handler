"""Server commands for managing configured servers and running local servers."""

from __future__ import annotations

import os
import stat
import tempfile
import tomllib
from pathlib import Path
from typing import Optional

import click

from a2a_handler.common import Output, get_logger
from a2a_handler.server import run_server
from a2a_handler.servers import (
    SERVERS_FILENAME,
    SERVER_SCHEMA_VERSION,
    ServerCatalog,
    ServerDefinition,
    ServerSource,
    find_git_root,
    load_server_catalog,
    resolve_server_credentials,
    server_file_path,
    server_source_label,
)
from a2a_handler.webhook import run_webhook_server

log = get_logger(__name__)


@click.group()
def server() -> None:
    """Manage configured servers and run local servers."""
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _server_to_dict(server_def: ServerDefinition) -> dict[str, object]:
    data: dict[str, object] = {
        "name": server_def.name,
        "source": server_source_label(server_def.source).lower(),
        "url": server_def.agent_url,
    }
    if server_def.auth:
        auth: dict[str, object] = {"type": server_def.auth.auth_type.value}
        if server_def.auth.env_var:
            auth["env_var"] = server_def.auth.env_var
        if server_def.auth.auth_type.value == "api_key":
            auth["header"] = server_def.auth.header_name
        if server_def.auth.cert_path:
            auth["cert_path"] = server_def.auth.cert_path
        if server_def.auth.key_path:
            auth["key_path"] = server_def.auth.key_path
        if server_def.auth.ca_cert_path:
            auth["ca_cert_path"] = server_def.auth.ca_cert_path
        data["auth"] = auth
    else:
        data["auth"] = None
    return data


def _iter_catalog_sections(
    catalog: ServerCatalog,
) -> list[tuple[ServerSource, tuple[ServerDefinition, ...]]]:
    return [
        (ServerSource.REPOSITORY, catalog.repository_servers),
        (ServerSource.GLOBAL, catalog.global_servers),
    ]


def _resolve_servers_path(use_repository: bool) -> Path:
    """Return the servers.toml path for the chosen scope."""
    if use_repository:
        git_root = find_git_root()
        if git_root is None:
            raise click.ClickException("Not in a git repository")
        return git_root / ".handler" / SERVERS_FILENAME
    return server_file_path()


_OWNER_RW = stat.S_IRUSR | stat.S_IWUSR  # 0o600


def _set_owner_only_permissions(path: Path) -> None:
    try:
        path.chmod(_OWNER_RW)
    except OSError:
        pass


def _toml_encode_value(value: object) -> str:
    """Encode a single value as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(value, list):
        items = ", ".join(_toml_encode_value(v) for v in value)
        return f"[{items}]"
    return repr(value)


def _read_toml(path: Path) -> dict[str, object]:
    """Read and parse a TOML file, returning an empty dict if missing."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _write_servers_toml(path: Path, data: dict[str, object]) -> None:
    """Atomically write a servers.toml from a data dict."""
    lines = [f"version = {SERVER_SCHEMA_VERSION}", ""]

    servers = data.get("servers")
    if isinstance(servers, dict):
        for name, entry in sorted(servers.items()):
            if not isinstance(entry, dict):
                continue
            lines.append(f"[servers.{name}]")
            for key, value in entry.items():
                if key == "auth":
                    continue
                lines.append(f"{key} = {_toml_encode_value(value)}")

            auth = entry.get("auth")
            if isinstance(auth, dict):
                lines.append("")
                lines.append(f"[servers.{name}.auth]")
                for key, value in auth.items():
                    lines.append(f"{key} = {_toml_encode_value(value)}")
            lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=".servers-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as tmp_file:
            tmp_file.write("\n".join(lines) + "\n")
        os.replace(tmp_path, path)
    except BaseException:
        with __import__("contextlib").suppress(OSError):
            os.unlink(tmp_path)
        raise

    _set_owner_only_permissions(path)


# ---------------------------------------------------------------------------
# Management commands
# ---------------------------------------------------------------------------


@server.command("list")
def server_list() -> None:
    """List configured repository and global servers.

    \b
    Examples:
      $ handler server list
    """
    output = Output()
    catalog = load_server_catalog()

    servers = [
        _server_to_dict(server_def)
        for source, server_defs in _iter_catalog_sections(catalog)
        for server_def in server_defs
    ]
    output.json(servers)


@server.command("show")
@click.argument("name")
@click.option(
    "--source",
    type=click.Choice(["repository", "global"]),
    help="Restrict lookup to a specific server source",
)
def server_show(name: str, source: str | None) -> None:
    """Show details for a configured server.

    \b
    Examples:
      $ handler server show my_agent
      $ handler server show my_agent --source global
    """
    output = Output()
    catalog = load_server_catalog()

    matches: list[ServerDefinition] = []
    for server_source, servers in _iter_catalog_sections(catalog):
        if source and server_source.value != source:
            continue
        matches.extend(server_def for server_def in servers if server_def.name == name)

    if not matches:
        output.error(code="not_found", message=f"Server '{name}' not found")
        return

    if len(matches) > 1:
        output.error(
            code="ambiguous_server",
            message=f"Server '{name}' exists in multiple sources; re-run with --source",
        )
        return

    server_def = matches[0]

    result = _server_to_dict(server_def)
    credentials, warning = resolve_server_credentials(server_def)
    result["credentials_status"] = (
        "resolved" if credentials else ("unavailable" if warning else "none")
    )
    if warning:
        result["credentials_warning"] = warning
    output.json(result)


@server.command("add")
@click.argument("name")
@click.option("--url", required=True, help="Server URL")
@click.option("--bearer", "bearer_token", help="Bearer token for authentication")
@click.option("--api-key", help="API key for authentication")
@click.option(
    "--api-key-header",
    default="X-API-Key",
    show_default=True,
    help="Header name for API key authentication",
)
@click.option("--cert", "cert_path", help="Client certificate path for mTLS")
@click.option("--key", "key_path", help="Client private key path for mTLS")
@click.option(
    "--global",
    "use_global",
    is_flag=True,
    default=True,
    help="Add to global config (default)",
)
@click.option(
    "--repository",
    "use_repository",
    is_flag=True,
    help="Add to repository-local config",
)
def server_add(
    name: str,
    url: str,
    bearer_token: str | None,
    api_key: str | None,
    api_key_header: str,
    cert_path: str | None,
    key_path: str | None,
    use_global: bool,
    use_repository: bool,
) -> None:
    """Add a server to the configuration.

    \b
    Examples:
      $ handler server add my_agent --url http://localhost:8000
      $ handler server add my_agent --url http://localhost:8000 --bearer TOKEN
      $ handler server add my_agent --url http://localhost:8000 --api-key KEY
      $ handler server add my_agent --url http://localhost:8000 --cert client.crt --key client.key
      $ handler server add my_agent --url http://localhost:8000 --repository
    """
    output = Output()
    path = _resolve_servers_path(use_repository)

    data = _read_toml(path)
    servers = data.get("servers", {})
    if isinstance(servers, dict) and name in servers:
        output.error(
            code="already_exists", message=f"Server '{name}' already exists in {path}"
        )
        return

    if not isinstance(servers, dict):
        servers = {}
    entry: dict[str, object] = {"url": url}

    if cert_path and key_path:
        entry["auth"] = {"type": "mtls", "cert": cert_path, "key": key_path}
    elif bearer_token:
        entry["auth"] = {"type": "bearer", "value": bearer_token}
    elif api_key:
        auth: dict[str, object] = {"type": "api_key", "value": api_key}
        if api_key_header != "X-API-Key":
            auth["header"] = api_key_header
        entry["auth"] = auth

    servers[name] = entry
    data["servers"] = servers
    data["version"] = SERVER_SCHEMA_VERSION

    _write_servers_toml(path, data)

    output.json({"name": name, "url": url, "path": str(path)})


@server.command("remove")
@click.argument("name")
@click.option(
    "--global",
    "use_global",
    is_flag=True,
    default=True,
    help="Remove from global config (default)",
)
@click.option(
    "--repository",
    "use_repository",
    is_flag=True,
    help="Remove from repository-local config",
)
def server_remove(name: str, use_global: bool, use_repository: bool) -> None:
    """Remove a server from the configuration.

    \b
    Examples:
      $ handler server remove my_agent
      $ handler server remove my_agent --repository
    """
    output = Output()
    path = _resolve_servers_path(use_repository)

    if not path.exists():
        output.error(code="not_found", message=f"No server file found at {path}")
        return

    data = _read_toml(path)
    servers = data.get("servers")
    if not isinstance(servers, dict) or name not in servers:
        output.error(code="not_found", message=f"Server '{name}' not found in {path}")
        return

    del servers[name]
    _write_servers_toml(path, data)

    output.json({"name": name, "path": str(path)})


@server.command("validate")
def server_validate() -> None:
    """Validate configured servers and default auth resolution.

    \b
    Examples:
      $ handler server validate
    """
    output = Output()
    catalog = load_server_catalog()

    results = []
    for source, servers in _iter_catalog_sections(catalog):
        for server_def in servers:
            entry = _server_to_dict(server_def)
            if server_def.auth:
                credentials, warning = resolve_server_credentials(server_def)
                entry["credentials_status"] = "ok" if credentials else "error"
                if warning:
                    entry["credentials_warning"] = warning
            results.append(entry)
    output.json(results)


# ---------------------------------------------------------------------------
# Run subgroup
# ---------------------------------------------------------------------------


@server.group("run")
def server_run() -> None:
    """Run local servers."""
    pass


@server_run.command("agent")
@click.option("--host", default="0.0.0.0", help="Host to bind to", show_default=True)
@click.option("--port", default=8000, help="Port to bind to", show_default=True)
@click.option("--auth/--no-auth", default=False, help="Require API key authentication")
@click.option(
    "--api-key",
    default=None,
    help="Specific API key to use (auto-generated if not set)",
)
@click.option(
    "--model",
    "-m",
    default=None,
    help="Model to use (e.g., 'llama3.2:1b', 'qwen3', 'gemini-2.0-flash')",
)
def server_agent(
    host: str,
    port: int,
    auth: bool,
    api_key: Optional[str],
    model: Optional[str],
) -> None:
    """Start a local A2A agent server.

    \b
    Examples:
      $ handler server run agent
      $ handler server run agent --port 9000
      $ handler server run agent --auth --api-key my-secret
      $ handler server run agent --model gemini-2.0-flash
    """
    log.info("Starting A2A server on %s:%d", host, port)
    run_server(
        host=host,
        port=port,
        require_auth=auth,
        api_key=api_key,
        model=model,
    )


@server_run.command("push")
@click.option("--host", default="127.0.0.1", help="Host to bind to", show_default=True)
@click.option("--port", default=9000, help="Port to bind to", show_default=True)
def server_push(host: str, port: int) -> None:
    """Start a local webhook server for receiving push notifications.

    \b
    Examples:
      $ handler server run push
      $ handler server run push --port 9001
    """
    log.info("Starting webhook server on %s:%d", host, port)
    run_webhook_server(host, port)
