"""Connection profile loading and auth resolution.

Profiles are defined in ``~/.handler/profiles.toml`` and allow naming agent
endpoints with optional authentication sources.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_api_key_auth,
    create_bearer_auth,
)
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    reject_control_chars,
    validate_agent_url,
)

logger = get_logger(__name__)

DEFAULT_PROFILE_DIRECTORY = Path.home() / ".handler"
PROFILE_FILENAME = "profiles.toml"
PROFILE_SCHEMA_VERSION = 1
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ProfileAuthConfig:
    """Authentication config for a named connection profile."""

    auth_type: AuthType
    env_var: str | None = None
    value: str | None = None
    header_name: str = "X-API-Key"


@dataclass(frozen=True, slots=True)
class ConnectionProfile:
    """Named connection profile loaded from ``profiles.toml``."""

    name: str
    agent_url: str
    use_session: bool = True
    auth: ProfileAuthConfig | None = None


class ProfileConfigError(ValueError):
    """Raised when profile configuration is malformed."""


def profile_file_path(profile_directory: Path | None = None) -> Path:
    """Get path to the profile TOML file."""
    directory = profile_directory or DEFAULT_PROFILE_DIRECTORY
    return directory / PROFILE_FILENAME


def load_profiles(
    profile_directory: Path | None = None,
) -> dict[str, ConnectionProfile]:
    """Load and validate profiles from disk.

    Invalid profiles are skipped with warnings so one broken profile does not
    prevent loading other valid profiles.
    """

    path = profile_file_path(profile_directory)
    if not path.exists():
        return {}

    try:
        with open(path, "rb") as profile_file:
            raw = tomllib.load(profile_file)
    except tomllib.TOMLDecodeError as error:
        logger.warning("Failed to parse profile file %s: %s", path, error)
        return {}
    except OSError as error:
        logger.warning("Failed to read profile file %s: %s", path, error)
        return {}

    try:
        raw_table = _coerce_str_key_table(raw, "root")
    except ProfileConfigError:
        logger.warning("Ignoring profile file %s: root must be a TOML table", path)
        return {}

    raw_version = raw_table.get("version", PROFILE_SCHEMA_VERSION)
    if raw_version != PROFILE_SCHEMA_VERSION:
        logger.warning(
            "Ignoring profile file %s: unsupported version %r (expected %d)",
            path,
            raw_version,
            PROFILE_SCHEMA_VERSION,
        )
        return {}

    raw_profiles_value = raw_table.get("profiles")
    if raw_profiles_value is None:
        return {}

    try:
        raw_profiles = _coerce_str_key_table(raw_profiles_value, "profiles")
    except ProfileConfigError:
        logger.warning(
            "Ignoring profile file %s: 'profiles' must be a TOML table", path
        )
        return {}

    loaded: dict[str, ConnectionProfile] = {}
    for name, profile_data in raw_profiles.items():
        try:
            loaded_profile = _parse_profile(name, profile_data)
        except ProfileConfigError as error:
            logger.warning("Skipping invalid profile %s: %s", name, error)
            continue
        loaded[loaded_profile.name] = loaded_profile

    return loaded


def resolve_profile_credentials(
    profile: ConnectionProfile,
) -> tuple[AuthCredentials | None, str | None]:
    """Resolve runtime credentials for a profile.

    Returns a tuple of ``(credentials, warning)``. ``warning`` is populated
    when a configured profile auth source cannot be resolved, for example when
    an expected environment variable is missing.
    """

    if profile.auth is None:
        return None, None

    auth = profile.auth
    value: str | None = None

    if auth.env_var:
        env_value = os.getenv(auth.env_var)
        if env_value:
            value = env_value
        elif auth.value is None:
            return (
                None,
                (
                    f"Profile '{profile.name}' expects environment variable "
                    f"{auth.env_var} for authentication"
                ),
            )

    if value is None:
        value = auth.value

    if not value:
        return (
            None,
            f"Profile '{profile.name}' has no non-empty auth value to use",
        )

    try:
        reject_control_chars(value, f"profiles.{profile.name}.auth")
    except InputValidationError:
        return (
            None,
            f"Profile '{profile.name}' auth value contains unsupported control characters",
        )

    if auth.auth_type == AuthType.BEARER:
        return create_bearer_auth(value), None

    return create_api_key_auth(value, header_name=auth.header_name), None


def _parse_profile(name: object, profile_data: object) -> ConnectionProfile:
    if not isinstance(name, str) or not name:
        raise ProfileConfigError("profile names must be non-empty strings")
    try:
        reject_control_chars(name, "profile_name")
    except InputValidationError as error:
        raise ProfileConfigError(error.message) from error

    profile_table = _coerce_str_key_table(profile_data, f"profiles.{name}")

    raw_url = profile_table.get("url")
    if not isinstance(raw_url, str) or not raw_url:
        raise ProfileConfigError("url must be a non-empty string")
    try:
        validate_agent_url(raw_url)
    except InputValidationError as error:
        raise ProfileConfigError(error.message) from error

    raw_use_session = profile_table.get("use_session", True)
    if not isinstance(raw_use_session, bool):
        raise ProfileConfigError("use_session must be a boolean")

    auth: ProfileAuthConfig | None = None
    if "auth" in profile_table:
        auth = _parse_profile_auth(profile_table.get("auth"))

    return ConnectionProfile(
        name=name,
        agent_url=raw_url,
        use_session=raw_use_session,
        auth=auth,
    )


def _parse_profile_auth(auth_data: object) -> ProfileAuthConfig:
    auth_table = _coerce_str_key_table(auth_data, "auth")

    raw_auth_type = auth_table.get("type")
    if not isinstance(raw_auth_type, str) or not raw_auth_type:
        raise ProfileConfigError("auth.type must be a non-empty string")

    normalized_auth_type = raw_auth_type.lower().replace("-", "_")
    try:
        auth_type = AuthType(normalized_auth_type)
    except ValueError as error:
        raise ProfileConfigError("auth.type must be one of: bearer, api_key") from error

    env_var = _parse_optional_str(auth_table, "env")
    literal_value = _parse_optional_str(auth_table, "value")

    if env_var is None and literal_value is None:
        raise ProfileConfigError("auth must define env or value")

    if env_var is not None:
        try:
            reject_control_chars(env_var, "auth.env")
        except InputValidationError as error:
            raise ProfileConfigError(error.message) from error
        if not _ENV_NAME_PATTERN.match(env_var):
            raise ProfileConfigError(
                "auth.env must be a valid environment variable name"
            )

    if literal_value is not None:
        try:
            reject_control_chars(literal_value, "auth.value")
        except InputValidationError as error:
            raise ProfileConfigError(error.message) from error

    header_name = "X-API-Key"
    if auth_type == AuthType.API_KEY:
        raw_header_name = auth_table.get("header", "X-API-Key")
        if not isinstance(raw_header_name, str) or not raw_header_name:
            raise ProfileConfigError("auth.header must be a non-empty string")
        try:
            reject_control_chars(raw_header_name, "auth.header")
        except InputValidationError as error:
            raise ProfileConfigError(error.message) from error
        header_name = raw_header_name
    elif "header" in auth_table:
        raise ProfileConfigError("auth.header is only valid for api_key auth")

    return ProfileAuthConfig(
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
        raise ProfileConfigError(f"auth.{field} must be a string")
    return value


def _coerce_str_key_table(value: object, field_name: str) -> dict[str, object]:
    """Validate and coerce a TOML table to ``dict[str, object]``."""
    if not isinstance(value, dict):
        raise ProfileConfigError(f"{field_name} must be a TOML table")

    table: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ProfileConfigError(f"{field_name} keys must be strings")
        table[key] = item
    return table
