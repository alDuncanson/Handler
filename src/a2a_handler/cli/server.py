"""Server commands for managing configured servers and running local servers."""

from __future__ import annotations

import os
import stat
import tempfile
import tomllib
from pathlib import Path
from typing import cast

import click

from a2a_handler.common import Output, get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    validate_header_name,
)
from a2a_handler.servers import (
    SERVERS_FILENAME,
    SERVER_SCHEMA_VERSION,
    ServerCatalog,
    ServerDefinition,
    ServerLoadDiagnostic,
    ServerLoadResult,
    ServerSource,
    find_git_root,
    inspect_servers_file,
    load_server_catalog,
    resolve_server_credentials,
    server_file_path,
    server_source_label,
    validate_server_definition,
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
        if server_def.auth.token_url:
            auth["token_url"] = server_def.auth.token_url
        if server_def.auth.client_id_env:
            auth["client_id_env"] = server_def.auth.client_id_env
        if server_def.auth.client_secret_env:
            auth["client_secret_env"] = server_def.auth.client_secret_env
        if server_def.auth.scopes:
            auth["scopes"] = list(server_def.auth.scopes)
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


def _toml_encode_key(key: str) -> str:
    """Encode a TOML key so names with dots or spaces remain addressable."""
    return _toml_encode_value(key)


def _read_toml(path: Path) -> dict[str, object]:
    """Read and parse a TOML file, returning an empty dict if missing."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _as_toml_table(value: object) -> dict[str, object] | None:
    """Narrow parsed TOML values to string-keyed dictionaries."""
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


def _inspect_server_sources() -> list[ServerLoadResult]:
    """Inspect the repository and global server files for loaded entries and issues."""
    results: list[ServerLoadResult] = []
    git_root = find_git_root()
    if git_root is not None:
        local_server_dir = git_root / ".handler"
        if local_server_dir != server_file_path().parent:
            results.append(
                inspect_servers_file(local_server_dir, ServerSource.REPOSITORY)
            )
    results.append(inspect_servers_file(None, ServerSource.GLOBAL))
    return results


def _diagnostic_to_dict(diagnostic: ServerLoadDiagnostic) -> dict[str, object]:
    """Serialize a server-load diagnostic for CLI output."""
    data: dict[str, object] = {
        "source": server_source_label(diagnostic.source).lower(),
        "path": str(diagnostic.path),
        "message": diagnostic.message,
    }
    if diagnostic.server_name is not None:
        data["name"] = diagnostic.server_name
    return data


def _build_server_auth_entry(
    *,
    bearer_env: str | None,
    api_key_env: str | None,
    api_key_header: str,
    cert_path: str | None,
    key_path: str | None,
    oauth2_token_url: str | None,
    oauth2_client_id_env: str | None,
    oauth2_client_secret_env: str | None,
    oauth2_scopes: tuple[str, ...],
) -> tuple[dict[str, object] | None, str | None]:
    """Build the auth table for a new server or return a validation error."""
    has_mtls = cert_path is not None or key_path is not None
    has_oauth2 = any(
        (
            oauth2_token_url,
            oauth2_client_id_env,
            oauth2_client_secret_env,
            oauth2_scopes,
        )
    )
    configured_methods = sum(
        bool(enabled)
        for enabled in (
            bearer_env,
            api_key_env,
            has_mtls,
            has_oauth2,
        )
    )
    if configured_methods > 1:
        return None, "Choose only one auth method when adding a server"

    if has_mtls:
        if not cert_path or not key_path:
            return None, "mTLS auth requires both --cert and --key"
        return {"type": "mtls", "cert": cert_path, "key": key_path}, None

    if bearer_env:
        return {"type": "bearer", "env": bearer_env}, None

    if api_key_env:
        try:
            validate_header_name(api_key_header, "api_key_header")
        except InputValidationError as error:
            return None, error.message
        auth: dict[str, object] = {"type": "api_key", "env": api_key_env}
        if api_key_header != "X-API-Key":
            auth["header"] = api_key_header
        return auth, None

    if has_oauth2:
        missing_flags = [
            flag
            for flag, value in (
                ("--oauth2-token-url", oauth2_token_url),
                ("--oauth2-client-id-env", oauth2_client_id_env),
                ("--oauth2-client-secret-env", oauth2_client_secret_env),
            )
            if not value
        ]
        if missing_flags:
            return None, ("OAuth2 auth requires " + ", ".join(missing_flags))

        auth = {
            "type": "oauth2",
            "token_url": oauth2_token_url,
            "client_id_env": oauth2_client_id_env,
            "client_secret_env": oauth2_client_secret_env,
        }
        if oauth2_scopes:
            auth["scopes"] = list(oauth2_scopes)
        return auth, None

    return None, None


def _write_servers_toml(path: Path, data: dict[str, object]) -> None:
    """Atomically write a servers.toml from a data dict."""
    lines = [f"version = {SERVER_SCHEMA_VERSION}", ""]

    servers = _as_toml_table(data.get("servers"))
    if servers is not None:
        for name, raw_entry in sorted(servers.items()):
            entry = _as_toml_table(raw_entry)
            if entry is None:
                continue
            encoded_name = _toml_encode_key(name)
            lines.append(f"[servers.{encoded_name}]")
            for key, value in entry.items():
                if key == "auth":
                    continue
                lines.append(f"{key} = {_toml_encode_value(value)}")

            auth = _as_toml_table(entry.get("auth"))
            if auth is not None:
                lines.append("")
                lines.append(f"[servers.{encoded_name}.auth]")
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
        diagnostics = [
            diagnostic
            for result in _inspect_server_sources()
            if not source or result.source.value == source
            for diagnostic in result.diagnostics
            if diagnostic.server_name == name
        ]
        if diagnostics:
            output.error(
                code="invalid_server_config",
                message=f"Server '{name}' exists but has invalid configuration",
                details={
                    "issues": [
                        _diagnostic_to_dict(diagnostic) for diagnostic in diagnostics
                    ]
                },
                suggestion="Run `handler server validate` to inspect configuration issues.",
            )
            return
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
@click.option("--bearer-env", help="Env var containing bearer token for authentication")
@click.option("--api-key-env", help="Env var containing API key for authentication")
@click.option(
    "--api-key-header",
    default="X-API-Key",
    show_default=True,
    help="Header name for API key authentication",
)
@click.option("--cert", "cert_path", help="Client certificate path for mTLS")
@click.option("--key", "key_path", help="Client private key path for mTLS")
@click.option("--oauth2-token-url", help="OAuth2 token URL for client credentials")
@click.option(
    "--oauth2-client-id-env",
    help="Env var containing the OAuth2 client ID",
)
@click.option(
    "--oauth2-client-secret-env",
    help="Env var containing the OAuth2 client secret",
)
@click.option(
    "--oauth2-scope",
    "oauth2_scopes",
    multiple=True,
    help="OAuth2 scope to request (repeatable)",
)
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
    bearer_env: str | None,
    api_key_env: str | None,
    api_key_header: str,
    cert_path: str | None,
    key_path: str | None,
    oauth2_token_url: str | None,
    oauth2_client_id_env: str | None,
    oauth2_client_secret_env: str | None,
    oauth2_scopes: tuple[str, ...],
    use_global: bool,
    use_repository: bool,
) -> None:
    """Add a server to the configuration.

    \b
    Examples:
      $ handler server add my_agent --url http://localhost:8000
      $ handler server add my_agent --url http://localhost:8000 --bearer-env MY_TOKEN
      $ handler server add my_agent --url http://localhost:8000 --api-key-env MY_KEY
      $ handler server add my_agent --url http://localhost:8000 --cert client.crt --key client.key
      $ handler server add my_agent --url http://localhost:8000 --oauth2-token-url https://auth.example.com/token --oauth2-client-id-env CLIENT_ID --oauth2-client-secret-env CLIENT_SECRET --oauth2-scope read
      $ handler server add my_agent --url http://localhost:8000 --repository
    """
    output = Output()
    path = _resolve_servers_path(use_repository)
    target_source = ServerSource.REPOSITORY if use_repository else ServerSource.GLOBAL

    data = _read_toml(path)
    servers = _as_toml_table(data.get("servers"))
    if servers is not None and name in servers:
        output.error(
            code="already_exists", message=f"Server '{name}' already exists in {path}"
        )
        return

    for result in _inspect_server_sources():
        if result.source == target_source:
            continue
        if any(server_def.name == name for server_def in result.servers):
            output.error(
                code="already_exists",
                message=(
                    f"Server '{name}' already exists in "
                    f"{server_source_label(result.source).lower()} config"
                ),
            )
            return
        conflicting_diagnostic = next(
            (
                diagnostic
                for diagnostic in result.diagnostics
                if diagnostic.server_name == name
            ),
            None,
        )
        if conflicting_diagnostic is not None:
            output.error(
                code="already_exists",
                message=(
                    f"Server '{name}' already exists as an invalid entry in "
                    f"{server_source_label(result.source).lower()} config"
                ),
                details=_diagnostic_to_dict(conflicting_diagnostic),
            )
            return

    if servers is None:
        servers = {}
    entry: dict[str, object] = {"url": url}

    auth_entry, auth_error = _build_server_auth_entry(
        bearer_env=bearer_env,
        api_key_env=api_key_env,
        api_key_header=api_key_header,
        cert_path=cert_path,
        key_path=key_path,
        oauth2_token_url=oauth2_token_url,
        oauth2_client_id_env=oauth2_client_id_env,
        oauth2_client_secret_env=oauth2_client_secret_env,
        oauth2_scopes=oauth2_scopes,
    )
    if auth_error:
        output.error(code="invalid_auth", message=auth_error)
        return
    if auth_entry is not None:
        entry["auth"] = auth_entry

    try:
        validate_server_definition(name, entry, target_source)
    except ValueError as error:
        output.error(code="invalid_server", message=str(error))
        return

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
    servers = _as_toml_table(data.get("servers"))
    if servers is None or name not in servers:
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

    results: list[dict[str, object]] = []
    for load_result in _inspect_server_sources():
        for diagnostic in load_result.diagnostics:
            issue = _diagnostic_to_dict(diagnostic)
            issue["status"] = "error"
            results.append(issue)

        for server_def in load_result.servers:
            entry = _server_to_dict(server_def)
            entry["path"] = str(load_result.path)
            entry["status"] = "ok"
            if server_def.auth:
                credentials, warning = resolve_server_credentials(server_def)
                entry["credentials_status"] = "ok" if credentials else "error"
                if warning:
                    entry["credentials_warning"] = warning
                    entry["status"] = "error"
            results.append(entry)
    output.json(results)


# ---------------------------------------------------------------------------
# Run subgroup
# ---------------------------------------------------------------------------


@server.group("run")
def server_run() -> None:
    """Run local servers."""
    pass


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
