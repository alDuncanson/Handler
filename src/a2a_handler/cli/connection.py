"""Connection commands for managing configured connection definitions."""

from __future__ import annotations

import rich_click as click

from a2a_handler.common import Output
from a2a_handler.connections import (
    ConnectionCatalog,
    ConnectionDefinition,
    ConnectionSource,
    connection_file_path,
    connection_source_label,
    find_git_root,
    load_connection_catalog,
    resolve_connection_credentials,
)


@click.group(name="connection")
def connection() -> None:
    """Manage configured connections."""
    pass


def _render_connection(output: Output, connection_def: ConnectionDefinition) -> None:
    output.field("Source", connection_source_label(connection_def.source))
    if connection_def.name:
        output.field("Name", connection_def.name)
    output.field("URL", connection_def.agent_url)
    if connection_def.auth:
        output.field("Auth Type", connection_def.auth.auth_type.value)
        if connection_def.auth.env_var:
            output.field("Env Var", connection_def.auth.env_var)
        if connection_def.auth.auth_type.value == "api_key":
            output.field("Header", connection_def.auth.header_name)
        if connection_def.auth.cert_path:
            output.field("Certificate", connection_def.auth.cert_path)
        if connection_def.auth.key_path:
            output.field("Private Key", connection_def.auth.key_path)
        if connection_def.auth.ca_cert_path:
            output.field("CA Certificate", connection_def.auth.ca_cert_path)
    else:
        output.field("Auth", "none", dim_value=True)


def _iter_catalog_sections(
    catalog: ConnectionCatalog,
) -> list[tuple[ConnectionSource, tuple[ConnectionDefinition, ...]]]:
    return [
        (ConnectionSource.REPOSITORY, catalog.repository_connections),
        (ConnectionSource.GLOBAL, catalog.global_connections),
    ]


@connection.command("list")
def connection_list() -> None:
    """List configured repository and global connections."""
    output = Output()
    catalog = load_connection_catalog()

    total = len(catalog.repository_connections) + len(catalog.global_connections)
    if total == 0:
        output.dim("No connections configured")
        output.dim(f"Create global connections in {connection_file_path()}")
        return

    for source, connections in _iter_catalog_sections(catalog):
        if not connections:
            continue
        output.header(
            f"{connection_source_label(source)} Connections ({len(connections)})"
        )
        for connection_def in connections:
            output.blank()
            output.subheader(connection_def.label)
            _render_connection(output, connection_def)


@connection.command("show")
@click.argument("name")
@click.option(
    "--source",
    type=click.Choice(["repository", "global"]),
    help="Restrict lookup to a specific connection source",
)
def connection_show(name: str, source: str | None) -> None:
    """Show details for a configured connection."""
    output = Output()
    catalog = load_connection_catalog()

    matches: list[ConnectionDefinition] = []
    for connection_source, connections in _iter_catalog_sections(catalog):
        if source and connection_source.value != source:
            continue
        matches.extend(
            connection_def
            for connection_def in connections
            if connection_def.name == name
        )

    if not matches:
        output.error(f"Connection '{name}' not found")
        return

    if len(matches) > 1:
        output.error(
            f"Connection '{name}' exists in multiple sources; re-run with --source"
        )
        return

    connection_def = matches[0]
    output.header(f"Connection: {connection_def.label}")
    _render_connection(output, connection_def)

    credentials, warning = resolve_connection_credentials(connection_def)
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
    """Validate configured connections and default auth resolution."""
    output = Output()
    catalog = load_connection_catalog()

    total = len(catalog.repository_connections) + len(catalog.global_connections)
    if total == 0:
        output.dim("No connections to validate")
        return

    output.header("Connection Validation")
    has_issues = False

    for source, connections in _iter_catalog_sections(catalog):
        for connection_def in connections:
            output.blank()
            output.subheader(
                f"{connection_source_label(source)}: {connection_def.label}"
            )
            output.field("URL", connection_def.agent_url)
            if not connection_def.auth:
                output.field("Auth", "none", dim_value=True)
                continue

            output.field("Auth Type", connection_def.auth.auth_type.value)
            credentials, warning = resolve_connection_credentials(connection_def)
            if credentials:
                output.field("Status", "ok", value_style="green")
            else:
                has_issues = True
                output.field("Status", "error", value_style="red")
                if warning:
                    output.warning(warning)

    output.blank()
    if has_issues:
        output.warning("Some connections have issues")
    else:
        output.success("All connections valid")


@connection.command("path")
def connection_path() -> None:
    """Show the configured connection file paths."""
    output = Output()

    global_path = connection_file_path()
    output.field("Global", str(global_path))

    git_root = find_git_root()
    if git_root:
        local_path = git_root / ".handler" / "connections.toml"
        output.field("Repository", str(local_path))
    else:
        output.field("Repository", "not in a git repository", dim_value=True)
