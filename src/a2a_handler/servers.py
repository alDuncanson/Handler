"""Server definition loading and auth resolution.

Servers are defined in ``$XDG_CONFIG_HOME/handler/servers.toml`` and optionally
in a repository-local ``.handler/servers.toml`` file at the git root.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from platformdirs import user_config_dir

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_api_key_auth,
    create_bearer_auth,
    create_mtls_auth,
    create_oauth2_auth,
)
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    reject_control_chars,
    validate_agent_url,
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
    cert_path: str | None = None
    key_path: str | None = None
    ca_cert_path: str | None = None
    # OAuth2 client credentials fields
    token_url: str | None = None
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


class ServerConfigError(ValueError):
    """Raised when server configuration is malformed."""


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

    path = server_file_path(server_directory)
    if not path.exists():
        return []

    try:
        with open(path, "rb") as server_file:
            raw = tomllib.load(server_file)
    except tomllib.TOMLDecodeError as error:
        logger.warning("Failed to parse server file %s: %s", path, error)
        return []
    except OSError as error:
        logger.warning("Failed to read server file %s: %s", path, error)
        return []

    try:
        raw_table = _coerce_str_key_table(raw, "root")
    except ServerConfigError:
        logger.warning("Ignoring server file %s: root must be a TOML table", path)
        return []

    raw_version = raw_table.get("version", SERVER_SCHEMA_VERSION)
    if raw_version != SERVER_SCHEMA_VERSION:
        logger.warning(
            "Ignoring server file %s: unsupported version %r (expected %d)",
            path,
            raw_version,
            SERVER_SCHEMA_VERSION,
        )
        return []

    raw_servers_value = raw_table.get("servers")
    if raw_servers_value is None:
        return []

    try:
        raw_servers = _coerce_str_key_table(raw_servers_value, "servers")
    except ServerConfigError:
        logger.warning("Ignoring server file %s: 'servers' must be a TOML table", path)
        return []

    loaded: list[ServerDefinition] = []
    for name, server_data in sorted(raw_servers.items()):
        try:
            loaded_server = _parse_server(name, server_data, source)
        except ServerConfigError as error:
            logger.warning("Skipping invalid server %s: %s", name, error)
            continue
        loaded.append(loaded_server)

    return loaded


def resolve_server_credentials(
    server_def: ServerDefinition,
) -> tuple[AuthCredentials | None, str | None]:
    """Resolve runtime credentials for a configured server."""
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
            return create_mtls_auth(
                auth.cert_path,
                auth.key_path,
                auth.ca_cert_path,
            ), None
        except FileNotFoundError as error:
            return None, f"Server '{server_name}': {error}"

    if auth.auth_type == AuthType.OAUTH2:
        if not auth.token_url or not auth.client_id_env or not auth.client_secret_env:
            return (
                None,
                f"Server '{server_name}' OAuth2 auth requires token_url, "
                "client_id_env, and client_secret_env",
            )
        client_id = os.getenv(auth.client_id_env)
        if not client_id:
            return (
                None,
                (
                    f"Server '{server_name}' expects environment variable "
                    f"{auth.client_id_env} for OAuth2 client ID"
                ),
            )
        client_secret = os.getenv(auth.client_secret_env)
        if not client_secret:
            return (
                None,
                (
                    f"Server '{server_name}' expects environment variable "
                    f"{auth.client_secret_env} for OAuth2 client secret"
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
                    f"Server '{server_name}' OAuth2 credentials contain "
                    "unsupported control characters"
                ),
            )
        return (
            create_oauth2_auth(auth.token_url, client_id, client_secret, auth.scopes),
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

    return create_api_key_auth(value, header_name=auth.header_name), None


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

    return ServerDefinition(
        server_id=f"{source.value}:{name}",
        source=source,
        name=name,
        agent_url=raw_url,
        auth=auth,
        origin_label=server_source_label(source),
    )


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
            "auth.type must be one of: bearer, api_key, mtls, oauth2"
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

    if auth_type == AuthType.OAUTH2:
        for forbidden in ("env", "value", "header"):
            if forbidden in auth_table:
                raise ServerConfigError(
                    f"auth.{forbidden} is not valid for oauth2 auth"
                )
        token_url = _parse_optional_str(auth_table, "token_url")
        if not token_url:
            raise ServerConfigError("oauth2 auth requires token_url")
        try:
            reject_control_chars(token_url, "auth.token_url")
        except InputValidationError as error:
            raise ServerConfigError(error.message) from error

        client_id_env = _parse_optional_str(auth_table, "client_id_env")
        client_secret_env = _parse_optional_str(auth_table, "client_secret_env")
        if not client_id_env or not client_secret_env:
            raise ServerConfigError(
                "oauth2 auth requires client_id_env and client_secret_env"
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
            scopes = list(raw_scopes)

        return ServerAuthConfig(
            auth_type=auth_type,
            token_url=token_url,
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
        except InputValidationError as error:
            raise ServerConfigError(error.message) from error
        header_name = raw_header_name
    elif "header" in auth_table:
        raise ServerConfigError("auth.header is only valid for api_key auth")

    return ServerAuthConfig(
        auth_type=auth_type,
        env_var=env_var,
        value=literal_value,
        header_name=header_name,
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
