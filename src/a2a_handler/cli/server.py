"""Server commands for managing configured servers and running local servers."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Optional

import click

from a2a_handler.common import Output, get_logger
from a2a_handler.server import run_server
from a2a_handler.servers import (
    DEFAULT_SERVER_DIRECTORY,
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


def _render_server(output: Output, server_def: ServerDefinition) -> None:
    output.field("Source", server_source_label(server_def.source))
    if server_def.name:
        output.field("Name", server_def.name)
    output.field("URL", server_def.agent_url)
    if server_def.auth:
        output.field("Auth Type", server_def.auth.auth_type.value)
        if server_def.auth.env_var:
            output.field("Env Var", server_def.auth.env_var)
        if server_def.auth.auth_type.value == "api_key":
            output.field("Header", server_def.auth.header_name)
        if server_def.auth.cert_path:
            output.field("Certificate", server_def.auth.cert_path)
        if server_def.auth.key_path:
            output.field("Private Key", server_def.auth.key_path)
        if server_def.auth.ca_cert_path:
            output.field("CA Certificate", server_def.auth.ca_cert_path)
    else:
        output.field("Auth", "none", dim_value=True)


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


def _build_toml_block(
    name: str,
    url: str,
    *,
    bearer_token: str | None,
    api_key: str | None,
    api_key_header: str,
    cert_path: str | None,
    key_path: str | None,
) -> str:
    """Build a TOML block for a single server entry."""
    lines = [f"[servers.{name}]", f'url = "{url}"']

    if cert_path and key_path:
        lines.append("")
        lines.append(f"[servers.{name}.auth]")
        lines.append('type = "mtls"')
        lines.append(f'cert = "{cert_path}"')
        lines.append(f'key = "{key_path}"')
    elif bearer_token:
        lines.append("")
        lines.append(f"[servers.{name}.auth]")
        lines.append('type = "bearer"')
        lines.append(f'value = "{bearer_token}"')
    elif api_key:
        lines.append("")
        lines.append(f"[servers.{name}.auth]")
        lines.append('type = "api_key"')
        lines.append(f'value = "{api_key}"')
        if api_key_header != "X-API-Key":
            lines.append(f'header = "{api_key_header}"')

    return "\n".join(lines) + "\n"


def _read_toml(path: Path) -> dict[str, object]:
    """Read and parse a TOML file, returning an empty dict if missing."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _write_toml_from_data(path: Path, data: dict[str, object]) -> None:
    """Rewrite a servers.toml from parsed data (without tomli_w)."""
    lines = [f"version = {SERVER_SCHEMA_VERSION}", ""]

    servers = data.get("servers")
    if isinstance(servers, dict):
        for name, entry in sorted(servers.items()):
            if not isinstance(entry, dict):
                continue
            lines.append(f"[servers.{name}]")
            url = entry.get("url", "")
            lines.append(f'url = "{url}"')

            auth = entry.get("auth")
            if isinstance(auth, dict):
                lines.append("")
                lines.append(f"[servers.{name}.auth]")
                for key, value in auth.items():
                    if isinstance(value, str):
                        lines.append(f'{key} = "{value}"')
            lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Management commands
# ---------------------------------------------------------------------------


@server.command("list")
def server_list() -> None:
    """List configured repository and global servers.

    **Examples:**

    ```
    handler server list
    ```
    """
    output = Output()
    catalog = load_server_catalog()

    total = len(catalog.repository_servers) + len(catalog.global_servers)
    if total == 0:
        output.dim("No servers configured")
        output.dim(f"Create global servers in {server_file_path()}")
        return

    for source, servers in _iter_catalog_sections(catalog):
        if not servers:
            continue
        output.header(
            f"{server_source_label(source)} Servers ({len(servers)})"
        )
        for server_def in servers:
            output.blank()
            output.subheader(server_def.label)
            _render_server(output, server_def)


@server.command("show")
@click.argument("name")
@click.option(
    "--source",
    type=click.Choice(["repository", "global"]),
    help="Restrict lookup to a specific server source",
)
def server_show(name: str, source: str | None) -> None:
    """Show details for a configured server.

    **Examples:**

    ```
    handler server show my_agent
    handler server show my_agent --source global
    ```
    """
    output = Output()
    catalog = load_server_catalog()

    matches: list[ServerDefinition] = []
    for server_source, servers in _iter_catalog_sections(catalog):
        if source and server_source.value != source:
            continue
        matches.extend(
            server_def
            for server_def in servers
            if server_def.name == name
        )

    if not matches:
        output.error(f"Server '{name}' not found")
        return

    if len(matches) > 1:
        output.error(
            f"Server '{name}' exists in multiple sources; re-run with --source"
        )
        return

    server_def = matches[0]
    output.header(f"Server: {server_def.label}")
    _render_server(output, server_def)

    credentials, warning = resolve_server_credentials(server_def)
    output.blank()
    if credentials:
        output.field("Status", "resolved", value_style="green")
    elif warning:
        output.field("Status", "unavailable", value_style="yellow")
        output.warning(warning)
    else:
        output.field("Status", "no default auth configured", dim_value=True)


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

    **Examples:**

    ```
    handler server add my_agent --url http://localhost:8000
    handler server add my_agent --url http://localhost:8000 --bearer TOKEN
    handler server add my_agent --url http://localhost:8000 --api-key KEY
    handler server add my_agent --url http://localhost:8000 --cert client.crt --key client.key
    handler server add my_agent --url http://localhost:8000 --repository
    ```
    """
    output = Output()
    path = _resolve_servers_path(use_repository)

    data = _read_toml(path)
    servers = data.get("servers", {})
    if isinstance(servers, dict) and name in servers:
        output.error(f"Server '{name}' already exists in {path}")
        return

    block = _build_toml_block(
        name,
        url,
        bearer_token=bearer_token,
        api_key=api_key,
        api_key_header=api_key_header,
        cert_path=cert_path,
        key_path=key_path,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w") as f:
            f.write(f"version = {SERVER_SCHEMA_VERSION}\n\n{block}")
    else:
        with open(path, "a") as f:
            f.write(f"\n{block}")

    output.success(f"Added server '{name}' to {path}")


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

    **Examples:**

    ```
    handler server remove my_agent
    handler server remove my_agent --repository
    ```
    """
    output = Output()
    path = _resolve_servers_path(use_repository)

    if not path.exists():
        output.error(f"No server file found at {path}")
        return

    data = _read_toml(path)
    servers = data.get("servers")
    if not isinstance(servers, dict) or name not in servers:
        output.error(f"Server '{name}' not found in {path}")
        return

    del servers[name]
    _write_toml_from_data(path, data)
    output.success(f"Removed server '{name}' from {path}")


@server.command("validate")
def server_validate() -> None:
    """Validate configured servers and default auth resolution.

    **Examples:**

    ```
    handler server validate
    ```
    """
    output = Output()
    catalog = load_server_catalog()

    total = len(catalog.repository_servers) + len(catalog.global_servers)
    if total == 0:
        output.dim("No servers to validate")
        return

    output.header("Server Validation")
    has_issues = False

    for source, servers in _iter_catalog_sections(catalog):
        for server_def in servers:
            output.blank()
            output.subheader(
                f"{server_source_label(source)}: {server_def.label}"
            )
            output.field("URL", server_def.agent_url)
            if not server_def.auth:
                output.field("Auth", "none", dim_value=True)
                continue

            output.field("Auth Type", server_def.auth.auth_type.value)
            credentials, warning = resolve_server_credentials(server_def)
            if credentials:
                output.field("Status", "ok", value_style="green")
            else:
                has_issues = True
                output.field("Status", "error", value_style="red")
                if warning:
                    output.warning(warning)

    output.blank()
    if has_issues:
        output.warning("Some servers have issues")
    else:
        output.success("All servers valid")


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

    **Examples:**

    ```
    handler server run agent
    handler server run agent --port 9000
    handler server run agent --auth --api-key my-secret
    handler server run agent --model gemini-2.0-flash
    ```
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

    **Examples:**

    ```
    handler server run push
    handler server run push --port 9001
    ```
    """
    log.info("Starting webhook server on %s:%d", host, port)
    run_webhook_server(host, port)
