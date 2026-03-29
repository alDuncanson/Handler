"""Connection definition loading and auth resolution.

Connections are defined in ``~/.handler/connections.toml`` and optionally in a
repository-local ``.handler/connections.toml`` file at the git root.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_api_key_auth,
    create_bearer_auth,
    create_mtls_auth,
)
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    reject_control_chars,
    validate_agent_url,
)

logger = get_logger(__name__)

DEFAULT_CONNECTION_DIRECTORY = Path.home() / ".handler"
CONNECTIONS_FILENAME = "connections.toml"
CONNECTION_SCHEMA_VERSION = 1
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConnectionSource(str, Enum):
    """Origin of a connection definition shown to the user."""

    REPOSITORY = "repository"
    GLOBAL = "global"
    RECENT = "recent"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ConnectionAuthConfig:
    """Authentication config for a named connection definition."""

    auth_type: AuthType
    env_var: str | None = None
    value: str | None = None
    header_name: str = "X-API-Key"
    cert_path: str | None = None
    key_path: str | None = None
    ca_cert_path: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectionDefinition:
    """A selectable connection option."""

    connection_id: str
    source: ConnectionSource
    name: str | None
    agent_url: str
    auth: ConnectionAuthConfig | None = None
    origin_label: str = ""

    @property
    def label(self) -> str:
        """Human-friendly label for selectors and summaries."""
        return self.name or self.agent_url


@dataclass(frozen=True, slots=True)
class ConnectionCatalog:
    """Configured repository and global connection definitions."""

    repository_connections: tuple[ConnectionDefinition, ...] = ()
    global_connections: tuple[ConnectionDefinition, ...] = ()

    def all_configured_urls(self) -> set[str]:
        """Return all configured URLs across repository and global sources."""
        return {
            connection.agent_url
            for connection in (
                *self.repository_connections,
                *self.global_connections,
            )
        }


class ConnectionConfigError(ValueError):
    """Raised when connection configuration is malformed."""


def connection_source_label(source: ConnectionSource) -> str:
    """Human-readable label for a connection source."""
    labels = {
        ConnectionSource.REPOSITORY: "Repository",
        ConnectionSource.GLOBAL: "Global",
        ConnectionSource.RECENT: "Recent",
        ConnectionSource.MANUAL: "Manual",
    }
    return labels[source]


def connection_file_path(connection_directory: Path | None = None) -> Path:
    """Get path to the connection TOML file."""
    directory = connection_directory or DEFAULT_CONNECTION_DIRECTORY
    return directory / CONNECTIONS_FILENAME


def load_connections(
    connection_directory: Path | None,
    source: ConnectionSource,
) -> list[ConnectionDefinition]:
    """Load and validate connection definitions from disk.

    Invalid connections are skipped with warnings so one broken connection does
    not prevent loading the others.
    """

    path = connection_file_path(connection_directory)
    if not path.exists():
        return []

    try:
        with open(path, "rb") as connection_file:
            raw = tomllib.load(connection_file)
    except tomllib.TOMLDecodeError as error:
        logger.warning("Failed to parse connection file %s: %s", path, error)
        return []
    except OSError as error:
        logger.warning("Failed to read connection file %s: %s", path, error)
        return []

    try:
        raw_table = _coerce_str_key_table(raw, "root")
    except ConnectionConfigError:
        logger.warning("Ignoring connection file %s: root must be a TOML table", path)
        return []

    raw_version = raw_table.get("version", CONNECTION_SCHEMA_VERSION)
    if raw_version != CONNECTION_SCHEMA_VERSION:
        logger.warning(
            "Ignoring connection file %s: unsupported version %r (expected %d)",
            path,
            raw_version,
            CONNECTION_SCHEMA_VERSION,
        )
        return []

    raw_connections_value = raw_table.get("connections")
    if raw_connections_value is None:
        return []

    try:
        raw_connections = _coerce_str_key_table(raw_connections_value, "connections")
    except ConnectionConfigError:
        logger.warning(
            "Ignoring connection file %s: 'connections' must be a TOML table", path
        )
        return []

    loaded: list[ConnectionDefinition] = []
    for name, connection_data in sorted(raw_connections.items()):
        try:
            loaded_connection = _parse_connection(name, connection_data, source)
        except ConnectionConfigError as error:
            logger.warning("Skipping invalid connection %s: %s", name, error)
            continue
        loaded.append(loaded_connection)

    return loaded


def resolve_connection_credentials(
    connection: ConnectionDefinition,
) -> tuple[AuthCredentials | None, str | None]:
    """Resolve runtime credentials for a configured connection."""
    if connection.auth is None:
        return None, None

    auth = connection.auth
    connection_name = connection.name or connection.agent_url

    if auth.auth_type == AuthType.MTLS:
        if not auth.cert_path or not auth.key_path:
            return (
                None,
                f"Connection '{connection_name}' mTLS auth requires cert and key paths",
            )
        try:
            return create_mtls_auth(
                auth.cert_path,
                auth.key_path,
                auth.ca_cert_path,
            ), None
        except FileNotFoundError as error:
            return None, f"Connection '{connection_name}': {error}"

    value: str | None = None
    if auth.env_var:
        env_value = os.getenv(auth.env_var)
        if env_value:
            value = env_value
        elif auth.value is None:
            return (
                None,
                (
                    f"Connection '{connection_name}' expects environment variable "
                    f"{auth.env_var} for authentication"
                ),
            )

    if value is None:
        value = auth.value

    if not value:
        return (
            None,
            f"Connection '{connection_name}' has no non-empty auth value to use",
        )

    try:
        reject_control_chars(value, f"connections.{connection_name}.auth")
    except InputValidationError:
        return (
            None,
            (
                f"Connection '{connection_name}' auth value contains unsupported "
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


def load_connection_catalog(
    connection_directory: Path | None = None,
) -> ConnectionCatalog:
    """Load global and repository-local connection definitions."""
    global_connections = tuple(
        load_connections(connection_directory, ConnectionSource.GLOBAL)
    )

    repository_connections: tuple[ConnectionDefinition, ...] = ()
    git_root = find_git_root()
    if git_root is not None:
        local_connection_dir = git_root / ".handler"
        if local_connection_dir != (
            connection_directory or DEFAULT_CONNECTION_DIRECTORY
        ):
            repository_connections = tuple(
                load_connections(local_connection_dir, ConnectionSource.REPOSITORY)
            )

    return ConnectionCatalog(
        repository_connections=repository_connections,
        global_connections=global_connections,
    )


def _parse_connection(
    name: object,
    connection_data: object,
    source: ConnectionSource,
) -> ConnectionDefinition:
    if not isinstance(name, str) or not name:
        raise ConnectionConfigError("connection names must be non-empty strings")
    try:
        reject_control_chars(name, "connection_name")
    except InputValidationError as error:
        raise ConnectionConfigError(error.message) from error

    connection_table = _coerce_str_key_table(connection_data, f"connections.{name}")

    raw_url = connection_table.get("url")
    if not isinstance(raw_url, str) or not raw_url:
        raise ConnectionConfigError("url must be a non-empty string")
    try:
        validate_agent_url(raw_url)
    except InputValidationError as error:
        raise ConnectionConfigError(error.message) from error

    auth: ConnectionAuthConfig | None = None
    if "auth" in connection_table:
        auth = _parse_connection_auth(connection_table.get("auth"))

    return ConnectionDefinition(
        connection_id=f"{source.value}:{name}",
        source=source,
        name=name,
        agent_url=raw_url,
        auth=auth,
        origin_label=connection_source_label(source),
    )


def _parse_connection_auth(auth_data: object) -> ConnectionAuthConfig:
    auth_table = _coerce_str_key_table(auth_data, "auth")

    raw_auth_type = auth_table.get("type")
    if not isinstance(raw_auth_type, str) or not raw_auth_type:
        raise ConnectionConfigError("auth.type must be a non-empty string")

    normalized_auth_type = raw_auth_type.lower().replace("-", "_")
    try:
        auth_type = AuthType(normalized_auth_type)
    except ValueError as error:
        raise ConnectionConfigError(
            "auth.type must be one of: bearer, api_key, mtls"
        ) from error

    if auth_type == AuthType.MTLS:
        for forbidden in ("env", "value", "header"):
            if forbidden in auth_table:
                raise ConnectionConfigError(
                    f"auth.{forbidden} is not valid for mtls auth"
                )
        cert = _parse_optional_str(auth_table, "cert")
        key = _parse_optional_str(auth_table, "key")
        if cert is None or key is None:
            raise ConnectionConfigError("mtls auth requires cert and key fields")
        try:
            reject_control_chars(cert, "auth.cert")
            reject_control_chars(key, "auth.key")
        except InputValidationError as error:
            raise ConnectionConfigError(error.message) from error
        ca_cert = _parse_optional_str(auth_table, "ca_cert")
        if ca_cert is not None:
            try:
                reject_control_chars(ca_cert, "auth.ca_cert")
            except InputValidationError as error:
                raise ConnectionConfigError(error.message) from error
        return ConnectionAuthConfig(
            auth_type=auth_type,
            cert_path=cert,
            key_path=key,
            ca_cert_path=ca_cert,
        )

    env_var = _parse_optional_str(auth_table, "env")
    literal_value = _parse_optional_str(auth_table, "value")

    if env_var is None and literal_value is None:
        raise ConnectionConfigError("auth must define env or value")

    if env_var is not None:
        try:
            reject_control_chars(env_var, "auth.env")
        except InputValidationError as error:
            raise ConnectionConfigError(error.message) from error
        if not _ENV_NAME_PATTERN.match(env_var):
            raise ConnectionConfigError(
                "auth.env must be a valid environment variable name"
            )

    if literal_value is not None:
        try:
            reject_control_chars(literal_value, "auth.value")
        except InputValidationError as error:
            raise ConnectionConfigError(error.message) from error

    header_name = "X-API-Key"
    if auth_type == AuthType.API_KEY:
        raw_header_name = auth_table.get("header", "X-API-Key")
        if not isinstance(raw_header_name, str) or not raw_header_name:
            raise ConnectionConfigError("auth.header must be a non-empty string")
        try:
            reject_control_chars(raw_header_name, "auth.header")
        except InputValidationError as error:
            raise ConnectionConfigError(error.message) from error
        header_name = raw_header_name
    elif "header" in auth_table:
        raise ConnectionConfigError("auth.header is only valid for api_key auth")

    return ConnectionAuthConfig(
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
        raise ConnectionConfigError(f"auth.{field} must be a string")
    return value


def _coerce_str_key_table(value: object, field_name: str) -> dict[str, object]:
    """Validate and coerce a TOML table to ``dict[str, object]``."""
    if not isinstance(value, dict):
        raise ConnectionConfigError(f"{field_name} must be a TOML table")

    table: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ConnectionConfigError(f"{field_name} keys must be strings")
        table[key] = item
    return table
