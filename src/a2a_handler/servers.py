"""Server definition loading and auth resolution.

Servers are defined in ``servers.toml`` under the platform's per-user config
directory (``platformdirs.user_config_dir("handler")``: for example
``~/Library/Application Support/handler`` on macOS and
``$XDG_CONFIG_HOME/handler`` on Linux) and optionally in a repository-local
``.handler/servers.toml`` file at the repository root.
"""

from __future__ import annotations

import os
import re
import ssl
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from platformdirs import user_config_dir

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_api_key_auth,
    create_basic_auth,
    create_bearer_auth,
    create_mtls_auth,
    create_oauth2_auth,
    create_oidc_auth,
)
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    reject_control_chars,
    validate_agent_url,
    validate_header_name,
    validate_token_url,
)

logger = get_logger(__name__)

DEFAULT_SERVER_DIRECTORY = Path(user_config_dir("handler"))
SERVERS_FILENAME = "servers.toml"
SERVER_SCHEMA_VERSION = 1
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ServerSource(str, Enum):
    """Origin of a server definition shown to the user."""

    REPOSITORY = "repository"
    GLOBAL = "global"
    RECENT = "recent"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ServerAuthConfig:
    """Authentication config for a named server definition."""

    auth_type: AuthType
    env_var: str | None = None
    value: str | None = None
    header_name: str = "X-API-Key"
    # HTTP basic field (the password comes from env/value)
    username: str | None = None
    cert_path: str | None = None
    key_path: str | None = None
    ca_cert_path: str | None = None
    # OAuth2 client credentials / OIDC fields
    token_url: str | None = None
    issuer_url: str | None = None
    client_id_env: str | None = None
    client_secret_env: str | None = None
    scopes: list[str] | None = None


@dataclass(frozen=True, slots=True)
class ServerDefinition:
    """A selectable server option."""

    server_id: str
    source: ServerSource
    name: str | None
    agent_url: str
    auth: ServerAuthConfig | None = None
    origin_label: str = ""
    #: A2A extension URIs to request on every call to this server.
    extensions: tuple[str, ...] = ()
    #: Static request headers sent on every call, as (name, value) pairs.
    headers: tuple[tuple[str, str], ...] = ()

    @property
    def label(self) -> str:
        """Human-friendly label for selectors and summaries."""
        return self.name or self.agent_url


@dataclass(frozen=True, slots=True)
class ServerCatalog:
    """Configured repository and global server definitions."""

    repository_servers: tuple[ServerDefinition, ...] = ()
    global_servers: tuple[ServerDefinition, ...] = ()

    def all_configured_urls(self) -> set[str]:
        """Return all configured URLs across repository and global sources."""
        return {
            server_def.agent_url
            for server_def in (
                *self.repository_servers,
                *self.global_servers,
            )
        }


class ServerLookupError(LookupError):
    """Raised when a named server cannot be resolved to exactly one entry."""


class ServerConfigError(ValueError):
    """Raised when server configuration is malformed."""


@dataclass(frozen=True, slots=True)
class ServerLoadDiagnostic:
    """Structured validation issue found while loading a server file."""

    path: Path
    source: ServerSource
    message: str
    server_name: str | None = None


@dataclass(frozen=True, slots=True)
class ServerLoadResult:
    """Loaded servers plus non-fatal diagnostics for one file."""

    path: Path
    source: ServerSource
    servers: tuple[ServerDefinition, ...] = ()
    diagnostics: tuple[ServerLoadDiagnostic, ...] = ()


def server_source_label(source: ServerSource) -> str:
    """Human-readable label for a server source."""
    labels = {
        ServerSource.REPOSITORY: "Repository",
        ServerSource.GLOBAL: "Global",
        ServerSource.RECENT: "Recent",
        ServerSource.MANUAL: "Manual",
    }
    return labels[source]


def server_file_path(server_directory: Path | None = None) -> Path:
    """Get path to the server TOML file."""
    directory = server_directory or DEFAULT_SERVER_DIRECTORY
    return directory / SERVERS_FILENAME


def load_servers(
    server_directory: Path | None,
    source: ServerSource,
) -> list[ServerDefinition]:
    """Load and validate server definitions from disk.

    Invalid servers are skipped with warnings so one broken server does
    not prevent loading the others.
    """

    result = inspect_servers_file(server_directory, source)
    for diagnostic in result.diagnostics:
        if diagnostic.server_name:
            logger.warning(
                "Skipping invalid server %s in %s: %s",
                diagnostic.server_name,
                diagnostic.path,
                diagnostic.message,
            )
        else:
            logger.warning(
                "Ignoring server file %s: %s", diagnostic.path, diagnostic.message
            )
    return list(result.servers)


def inspect_servers_file(
    server_directory: Path | None,
    source: ServerSource,
) -> ServerLoadResult:
    """Load one server file while preserving structured diagnostics."""
    path = server_file_path(server_directory)
    if not path.exists():
        return ServerLoadResult(path=path, source=source)

    diagnostics: list[ServerLoadDiagnostic] = []
    try:
        with open(path, "rb") as server_file:
            raw = tomllib.load(server_file)
    except tomllib.TOMLDecodeError as error:
        diagnostics.append(
            ServerLoadDiagnostic(
                path=path, source=source, message=f"Failed to parse TOML: {error}"
            )
        )
        return ServerLoadResult(
            path=path, source=source, diagnostics=tuple(diagnostics)
        )
    except OSError as error:
        diagnostics.append(
            ServerLoadDiagnostic(
                path=path, source=source, message=f"Failed to read file: {error}"
            )
        )
        return ServerLoadResult(
            path=path, source=source, diagnostics=tuple(diagnostics)
        )

    try:
        raw_table = _coerce_str_key_table(raw, "root")
    except ServerConfigError as error:
        diagnostics.append(
            ServerLoadDiagnostic(path=path, source=source, message=error.args[0])
        )
        return ServerLoadResult(
            path=path, source=source, diagnostics=tuple(diagnostics)
        )

    raw_version = raw_table.get("version", SERVER_SCHEMA_VERSION)
    if raw_version != SERVER_SCHEMA_VERSION:
        diagnostics.append(
            ServerLoadDiagnostic(
                path=path,
                source=source,
                message=(
                    f"unsupported version {raw_version!r} "
                    f"(expected {SERVER_SCHEMA_VERSION})"
                ),
            )
        )
        return ServerLoadResult(
            path=path, source=source, diagnostics=tuple(diagnostics)
        )

    raw_servers_value = raw_table.get("servers")
    if raw_servers_value is None:
        return ServerLoadResult(path=path, source=source)

    try:
        raw_servers = _coerce_str_key_table(raw_servers_value, "servers")
    except ServerConfigError as error:
        diagnostics.append(
            ServerLoadDiagnostic(path=path, source=source, message=error.args[0])
        )
        return ServerLoadResult(
            path=path, source=source, diagnostics=tuple(diagnostics)
        )

    loaded: list[ServerDefinition] = []
    for name, server_data in sorted(raw_servers.items()):
        try:
            loaded_server = _parse_server(name, server_data, source)
        except ServerConfigError as error:
            diagnostics.append(
                ServerLoadDiagnostic(
                    path=path,
                    source=source,
                    server_name=name if isinstance(name, str) else None,
                    message=error.args[0],
                )
            )
            continue
        loaded.append(loaded_server)

    return ServerLoadResult(
        path=path,
        source=source,
        servers=tuple(loaded),
        diagnostics=tuple(diagnostics),
    )


def resolve_server_credentials(
    server_def: ServerDefinition,
) -> tuple[AuthCredentials | None, str | None]:
    """Resolve runtime credentials for a configured server.

    Static headers from the entry ride along on the credentials, the same
    way ``-H`` does on the command line, so every surface sends them. A
    header given on the command line wins over the file's on a name clash.
    """
    credentials, warning = _resolve_server_auth(server_def)
    if warning or not server_def.headers:
        return credentials, warning
    headers = dict(server_def.headers)
    if credentials is None:
        return AuthCredentials(auth_type=AuthType.BEARER, custom_headers=headers), None
    credentials.custom_headers = {**headers, **(credentials.custom_headers or {})}
    return credentials, None


def _resolve_server_auth(
    server_def: ServerDefinition,
) -> tuple[AuthCredentials | None, str | None]:
    """Resolve the auth scheme's credentials, without the entry's headers."""
    if server_def.auth is None:
        return None, None

    auth = server_def.auth
    server_name = server_def.name or server_def.agent_url

    if auth.auth_type == AuthType.MTLS:
        if not auth.cert_path or not auth.key_path:
            return (
                None,
                f"Server '{server_name}' mTLS auth requires cert and key paths",
            )
        try:
            credentials = create_mtls_auth(
                auth.cert_path,
                auth.key_path,
                auth.ca_cert_path,
            )
            credentials.build_ssl_context()
            return credentials, None
        except FileNotFoundError as error:
            return None, f"Server '{server_name}': {error}"
        except (ssl.SSLError, OSError, ValueError) as error:
            return None, f"Server '{server_name}': {error}"

    if auth.auth_type in (AuthType.OAUTH2, AuthType.OIDC):
        scheme_label = "OAuth2" if auth.auth_type == AuthType.OAUTH2 else "OIDC"
        endpoint = (
            auth.token_url if auth.auth_type == AuthType.OAUTH2 else auth.issuer_url
        )
        endpoint_field = (
            "token_url" if auth.auth_type == AuthType.OAUTH2 else "issuer_url"
        )
        if not endpoint or not auth.client_id_env or not auth.client_secret_env:
            return (
                None,
                f"Server '{server_name}' {scheme_label} auth requires "
                f"{endpoint_field}, client_id_env, and client_secret_env",
            )
        client_id = os.getenv(auth.client_id_env)
        if not client_id:
            return (
                None,
                (
                    f"Server '{server_name}' expects environment variable "
                    f"{auth.client_id_env} for {scheme_label} client ID"
                ),
            )
        client_secret = os.getenv(auth.client_secret_env)
        if not client_secret:
            return (
                None,
                (
                    f"Server '{server_name}' expects environment variable "
                    f"{auth.client_secret_env} for {scheme_label} client secret"
                ),
            )
        try:
            reject_control_chars(client_id, f"servers.{server_name}.auth.client_id")
            reject_control_chars(
                client_secret, f"servers.{server_name}.auth.client_secret"
            )
        except InputValidationError:
            return (
                None,
                (
                    f"Server '{server_name}' {scheme_label} credentials contain "
                    "unsupported control characters"
                ),
            )
        if auth.auth_type == AuthType.OIDC:
            return (
                create_oidc_auth(endpoint, client_id, client_secret, auth.scopes),
                None,
            )
        return (
            create_oauth2_auth(endpoint, client_id, client_secret, auth.scopes),
            None,
        )

    value: str | None = None
    if auth.env_var:
        env_value = os.getenv(auth.env_var)
        if env_value:
            value = env_value
        elif auth.value is None:
            return (
                None,
                (
                    f"Server '{server_name}' expects environment variable "
                    f"{auth.env_var} for authentication"
                ),
            )

    if value is None:
        value = auth.value
        if value:
            logger.warning(literal_secret_warning(server_def))

    if not value:
        return (
            None,
            f"Server '{server_name}' has no non-empty auth value to use",
        )

    try:
        reject_control_chars(value, f"servers.{server_name}.auth")
    except InputValidationError:
        return (
            None,
            (
                f"Server '{server_name}' auth value contains unsupported "
                "control characters"
            ),
        )

    if auth.auth_type == AuthType.BEARER:
        return create_bearer_auth(value), None

    if auth.auth_type == AuthType.BASIC:
        if not auth.username:
            return (
                None,
                f"Server '{server_name}' basic auth requires username",
            )
        return create_basic_auth(auth.username, value), None

    return create_api_key_auth(value, header_name=auth.header_name), None


def literal_secret_warning(server_def: ServerDefinition) -> str | None:
    """Explain why a credential written straight into servers.toml is a risk.

    Nothing Handler writes produces ``auth.value``; only a hand-edited file
    does. It keeps working, but the file now holds the secret in plain text.
    """
    auth = server_def.auth
    if auth is None or not auth.value:
        return None
    name = server_def.name or server_def.agent_url
    return (
        f"Server '{name}' keeps its {auth.auth_type.value} credential as a "
        "literal `value` in servers.toml, in plain text; move it to an "
        'environment variable and reference it with `env = "VAR_NAME"`'
    )


def find_named_server(
    name: str, catalog: ServerCatalog | None = None
) -> ServerDefinition:
    """Resolve a named server across repository and global config.

    Fails closed on ambiguity: a name present in both sources is an error,
    not a silent pick. ``catalog`` defaults to the one on disk.
    """
    if catalog is None:
        catalog = load_server_catalog()
    matches = [
        server_def
        for server_def in (*catalog.repository_servers, *catalog.global_servers)
        if server_def.name == name
    ]
    if len(matches) > 1:
        raise ServerLookupError(
            f"Server '{name}' exists in multiple sources; use the URL or rename "
            "one entry."
        )
    if not matches:
        raise ServerLookupError(f"Server '{name}' not found in servers.toml.")
    return matches[0]


def find_git_root() -> Path | None:
    """Find the root of the current git repository, if any."""
    try:
        current = Path.cwd().resolve()
    except OSError:
        return None
    for directory in [current, *current.parents]:
        if (directory / ".git").exists():
            return directory
    return None


def load_server_catalog(
    server_directory: Path | None = None,
) -> ServerCatalog:
    """Load global and repository-local server definitions."""
    global_servers = tuple(load_servers(server_directory, ServerSource.GLOBAL))

    repository_servers: tuple[ServerDefinition, ...] = ()
    git_root = find_git_root()
    if git_root is not None:
        local_server_dir = git_root / ".handler"
        if local_server_dir != (server_directory or DEFAULT_SERVER_DIRECTORY):
            repository_servers = tuple(
                load_servers(local_server_dir, ServerSource.REPOSITORY)
            )

    return ServerCatalog(
        repository_servers=repository_servers,
        global_servers=global_servers,
    )


def validate_server_definition(
    name: object,
    server_data: object,
    source: ServerSource,
) -> ServerDefinition:
    """Validate one server entry using the shared loader rules."""
    return _parse_server(name, server_data, source)


def _parse_server(
    name: object,
    server_data: object,
    source: ServerSource,
) -> ServerDefinition:
    if not isinstance(name, str) or not name:
        raise ServerConfigError("server names must be non-empty strings")
    try:
        reject_control_chars(name, "server_name")
    except InputValidationError as error:
        raise ServerConfigError(error.message) from error

    server_table = _coerce_str_key_table(server_data, f"servers.{name}")

    raw_url = server_table.get("url")
    if not isinstance(raw_url, str) or not raw_url:
        raise ServerConfigError("url must be a non-empty string")
    try:
        validate_agent_url(raw_url)
    except InputValidationError as error:
        raise ServerConfigError(error.message) from error

    auth: ServerAuthConfig | None = None
    if "auth" in server_table:
        auth = _parse_server_auth(server_table.get("auth"))

    extensions: tuple[str, ...] = ()
    if "extensions" in server_table:
        extensions = _parse_server_extensions(server_table.get("extensions"))

    headers: tuple[tuple[str, str], ...] = ()
    if "headers" in server_table:
        headers = _parse_server_headers(server_table.get("headers"))

    return ServerDefinition(
        server_id=f"{source.value}:{name}",
        source=source,
        name=name,
        agent_url=raw_url,
        auth=auth,
        origin_label=server_source_label(source),
        extensions=extensions,
        headers=headers,
    )


def _parse_server_headers(headers_data: object) -> tuple[tuple[str, str], ...]:
    """Validate a server's static request headers table.

    Names go through the same check as ``-H`` on the command line, so a file
    cannot smuggle in ``Authorization`` or a hop-by-hop header.
    """
    table = _coerce_str_key_table(headers_data, "headers")
    parsed: list[tuple[str, str]] = []
    for name, value in table.items():
        if not name.strip():
            raise ServerConfigError("headers keys must be non-empty")
        if not isinstance(value, str) or not value:
            raise ServerConfigError(f"headers.{name} must be a non-empty string")
        try:
            reject_control_chars(name, "headers")
            reject_control_chars(value, f"headers.{name}")
            validate_header_name(name, "headers")
        except InputValidationError as error:
            raise ServerConfigError(error.message) from error
        parsed.append((name, value))
    return tuple(parsed)


def _parse_server_extensions(extensions_data: object) -> tuple[str, ...]:
    """Validate a server's requested A2A extension URI list."""
    if not isinstance(extensions_data, list) or not all(
        isinstance(uri, str) for uri in extensions_data
    ):
        raise ServerConfigError("extensions must be a list of strings")
    validated: list[str] = []
    for uri in extensions_data:
        if not isinstance(uri, str) or not uri.strip():
            raise ServerConfigError("extensions entries must be non-empty strings")
        try:
            reject_control_chars(uri, "extensions")
        except InputValidationError as error:
            raise ServerConfigError(error.message) from error
        validated.append(uri.strip())
    return tuple(validated)


def _parse_server_auth(auth_data: object) -> ServerAuthConfig:
    auth_table = _coerce_str_key_table(auth_data, "auth")

    raw_auth_type = auth_table.get("type")
    if not isinstance(raw_auth_type, str) or not raw_auth_type:
        raise ServerConfigError("auth.type must be a non-empty string")

    normalized_auth_type = raw_auth_type.lower().replace("-", "_")
    try:
        auth_type = AuthType(normalized_auth_type)
    except ValueError as error:
        raise ServerConfigError(
            "auth.type must be one of: bearer, basic, api_key, mtls, oauth2, oidc"
        ) from error

    if auth_type == AuthType.MTLS:
        for forbidden in ("env", "value", "header"):
            if forbidden in auth_table:
                raise ServerConfigError(f"auth.{forbidden} is not valid for mtls auth")
        cert = _parse_optional_str(auth_table, "cert")
        key = _parse_optional_str(auth_table, "key")
        if cert is None or key is None:
            raise ServerConfigError("mtls auth requires cert and key fields")
        try:
            reject_control_chars(cert, "auth.cert")
            reject_control_chars(key, "auth.key")
        except InputValidationError as error:
            raise ServerConfigError(error.message) from error
        ca_cert = _parse_optional_str(auth_table, "ca_cert")
        if ca_cert is not None:
            try:
                reject_control_chars(ca_cert, "auth.ca_cert")
            except InputValidationError as error:
                raise ServerConfigError(error.message) from error
        return ServerAuthConfig(
            auth_type=auth_type,
            cert_path=cert,
            key_path=key,
            ca_cert_path=ca_cert,
        )

    if auth_type in (AuthType.OAUTH2, AuthType.OIDC):
        for forbidden in ("env", "value", "header"):
            if forbidden in auth_table:
                raise ServerConfigError(
                    f"auth.{forbidden} is not valid for {auth_type.value} auth"
                )

        token_url: str | None = None
        issuer_url: str | None = None
        if auth_type == AuthType.OAUTH2:
            token_url = _parse_optional_str(auth_table, "token_url")
            if not token_url:
                raise ServerConfigError("oauth2 auth requires token_url")
        else:
            issuer_url = _parse_optional_str(auth_table, "issuer_url")
            if not issuer_url:
                raise ServerConfigError("oidc auth requires issuer_url")
        try:
            validate_token_url(token_url or issuer_url or "")
        except InputValidationError as error:
            raise ServerConfigError(error.message) from error

        client_id_env = _parse_optional_str(auth_table, "client_id_env")
        client_secret_env = _parse_optional_str(auth_table, "client_secret_env")
        if not client_id_env or not client_secret_env:
            raise ServerConfigError(
                f"{auth_type.value} auth requires client_id_env and client_secret_env"
            )
        for env_field, env_name in (
            ("client_id_env", client_id_env),
            ("client_secret_env", client_secret_env),
        ):
            try:
                reject_control_chars(env_name, f"auth.{env_field}")
            except InputValidationError as error:
                raise ServerConfigError(error.message) from error
            if not _ENV_NAME_PATTERN.match(env_name):
                raise ServerConfigError(
                    f"auth.{env_field} must be a valid environment variable name"
                )

        raw_scopes = auth_table.get("scopes")
        scopes: list[str] | None = None
        if raw_scopes is not None:
            if not isinstance(raw_scopes, list) or not all(
                isinstance(s, str) for s in raw_scopes
            ):
                raise ServerConfigError("auth.scopes must be a list of strings")
            scopes = [scope for scope in raw_scopes if isinstance(scope, str)]

        return ServerAuthConfig(
            auth_type=auth_type,
            token_url=token_url,
            issuer_url=issuer_url,
            client_id_env=client_id_env,
            client_secret_env=client_secret_env,
            scopes=scopes,
        )

    env_var = _parse_optional_str(auth_table, "env")
    literal_value = _parse_optional_str(auth_table, "value")

    if env_var is None and literal_value is None:
        raise ServerConfigError("auth must define env or value")

    if env_var is not None:
        try:
            reject_control_chars(env_var, "auth.env")
        except InputValidationError as error:
            raise ServerConfigError(error.message) from error
        if not _ENV_NAME_PATTERN.match(env_var):
            raise ServerConfigError(
                "auth.env must be a valid environment variable name"
            )

    if literal_value is not None:
        try:
            reject_control_chars(literal_value, "auth.value")
        except InputValidationError as error:
            raise ServerConfigError(error.message) from error

    header_name = "X-API-Key"
    if auth_type == AuthType.API_KEY:
        raw_header_name = auth_table.get("header", "X-API-Key")
        if not isinstance(raw_header_name, str) or not raw_header_name:
            raise ServerConfigError("auth.header must be a non-empty string")
        try:
            reject_control_chars(raw_header_name, "auth.header")
            validate_header_name(raw_header_name, "auth.header")
        except InputValidationError as error:
            raise ServerConfigError(error.message) from error
        header_name = raw_header_name
    elif "header" in auth_table:
        raise ServerConfigError("auth.header is only valid for api_key auth")

    username: str | None = None
    if auth_type == AuthType.BASIC:
        username = _parse_optional_str(auth_table, "username")
        if not username:
            raise ServerConfigError("basic auth requires username")
        try:
            reject_control_chars(username, "auth.username")
        except InputValidationError as error:
            raise ServerConfigError(error.message) from error
    elif "username" in auth_table:
        raise ServerConfigError("auth.username is only valid for basic auth")

    return ServerAuthConfig(
        auth_type=auth_type,
        env_var=env_var,
        value=literal_value,
        header_name=header_name,
        username=username,
    )


def _parse_optional_str(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ServerConfigError(f"auth.{field} must be a string")
    return value


def _coerce_str_key_table(value: object, field_name: str) -> dict[str, object]:
    """Validate and coerce a TOML table to ``dict[str, object]``."""
    if not isinstance(value, dict):
        raise ServerConfigError(f"{field_name} must be a TOML table")

    table: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ServerConfigError(f"{field_name} keys must be strings")
        table[key] = item
    return table
