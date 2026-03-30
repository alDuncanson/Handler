"""Connection commands for managing configured server definitions."""

from __future__ import annotations

import rich_click as click

from a2a_handler.common import Output
from a2a_handler.servers import (
    ServerCatalog,
    ServerDefinition,
    ServerSource,
    find_git_root,
    load_server_catalog,
    resolve_server_credentials,
    server_file_path,
    server_source_label,
)


@click.group(name="connection")
def connection() -> None:
    """Manage configured servers."""
    pass


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


@connection.command("list")
def connection_list() -> None:
    """List configured repository and global servers."""
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


@connection.command("show")
@click.argument("name")
@click.option(
    "--source",
    type=click.Choice(["repository", "global"]),
    help="Restrict lookup to a specific server source",
)
def connection_show(name: str, source: str | None) -> None:
    """Show details for a configured server."""
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


@connection.command("validate")
def connection_validate() -> None:
    """Validate configured servers and default auth resolution."""
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


@connection.command("path")
def connection_path() -> None:
    """Show the configured server file paths."""
    output = Output()

    global_path = server_file_path()
    output.field("Global", str(global_path))

    git_root = find_git_root()
    if git_root:
        local_path = git_root / ".handler" / "servers.toml"
        output.field("Repository", str(local_path))
    else:
        output.field("Repository", "not in a git repository", dim_value=True)
