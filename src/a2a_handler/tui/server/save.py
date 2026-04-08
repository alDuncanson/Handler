"""Save active TUI connections to the workspace server config."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import InputValidationError
from a2a_handler.servers import ServerAuthConfig

if TYPE_CHECKING:
    from a2a_handler.tui.server.tab import ServerTab

logger = get_logger(__name__)

_TOML_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _as_toml_table(value: object) -> dict[str, object] | None:
    """Narrow parsed TOML values to string-keyed dictionaries."""
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


def _sanitize_key(name: str) -> str:
    """Turn a display name into a safe TOML key."""
    key = name.strip().lower()
    key = re.sub(r"[^a-z0-9]+", "_", key)
    key = key.strip("_")
    return key or "server"


def _auth_config_to_dict(auth: ServerAuthConfig) -> dict[str, object]:
    """Convert a ServerAuthConfig to the TOML auth table dict."""
    entry: dict[str, object] = {"type": auth.auth_type.value}

    if auth.auth_type == AuthType.MTLS:
        if auth.cert_path:
            entry["cert"] = auth.cert_path
        if auth.key_path:
            entry["key"] = auth.key_path
        if auth.ca_cert_path:
            entry["ca_cert"] = auth.ca_cert_path
        return entry

    if auth.auth_type == AuthType.OAUTH2:
        if auth.token_url:
            entry["token_url"] = auth.token_url
        if auth.client_id_env:
            entry["client_id_env"] = auth.client_id_env
        if auth.client_secret_env:
            entry["client_secret_env"] = auth.client_secret_env
        if auth.scopes:
            entry["scopes"] = list(auth.scopes)
        return entry

    if auth.env_var:
        entry["env"] = auth.env_var
    elif auth.value:
        entry["value"] = auth.value

    if auth.auth_type == AuthType.API_KEY and auth.header_name != "X-API-Key":
        entry["header"] = auth.header_name

    return entry


def _credentials_to_skeleton_dict(
    credentials: AuthCredentials,
) -> dict[str, object] | None:
    """Build a skeleton auth dict from runtime credentials.

    Persists safe metadata (type, token_url, scopes, header name, file paths)
    and uses placeholder env var names for secrets so the user can fill them in.
    """
    entry: dict[str, object] = {"type": credentials.auth_type.value}

    if credentials.auth_type == AuthType.MTLS:
        if credentials.cert_path:
            entry["cert"] = credentials.cert_path
        if credentials.key_path:
            entry["key"] = credentials.key_path
        if credentials.ca_cert_path:
            entry["ca_cert"] = credentials.ca_cert_path
        return entry

    if credentials.auth_type == AuthType.OAUTH2:
        if credentials.token_url:
            entry["token_url"] = credentials.token_url
        entry["client_id_env"] = "CLIENT_ID"
        entry["client_secret_env"] = "CLIENT_SECRET"
        if credentials.scopes:
            entry["scopes"] = list(credentials.scopes)
        return entry

    if credentials.auth_type == AuthType.BEARER:
        entry["env"] = "BEARER_TOKEN"
        return entry

    if credentials.auth_type == AuthType.API_KEY:
        entry["env"] = "API_KEY"
        if credentials.header_name and credentials.header_name != "X-API-Key":
            entry["header"] = credentials.header_name
        return entry

    return None


def save_connections_to_workspace(
    connected_servers: list[ServerTab],
) -> int:
    """Save connected servers to the repository-local servers.toml.

    Returns the number of servers added (skips duplicates).
    """
    from a2a_handler.cli.server import (
        _read_toml,
        _resolve_servers_path,
        _write_servers_toml,
    )

    path = _resolve_servers_path(use_repository=True)
    data = _read_toml(path)
    servers = _as_toml_table(data.get("servers"))
    if servers is None:
        servers = {}

    existing_urls: set[str] = set()
    for raw_entry in servers.values():
        entry = _as_toml_table(raw_entry)
        if entry is None:
            continue
        url = entry.get("url")
        if isinstance(url, str):
            existing_urls.add(url)

    added = 0
    for server_tab in connected_servers:
        agent_url = server_tab.current_agent_url
        if not agent_url:
            continue

        if agent_url in existing_urls:
            logger.info("Skipping %s: already in workspace config", agent_url)
            continue

        card = server_tab.current_agent_card
        name = _sanitize_key(card.name if card else agent_url)

        # Ensure uniqueness
        base_name = name
        counter = 2
        while name in servers:
            name = f"{base_name}_{counter}"
            counter += 1

        entry: dict[str, object] = {"url": agent_url}

        server_def = server_tab.state.connected_server_def
        server_view = server_tab._try_get_server_view()
        if server_view is not None:
            try:
                panel_credentials = server_view.messages_panel().get_auth_credentials()
            except InputValidationError:
                logger.warning(
                    "Skipping auth metadata for %s due to invalid auth input",
                    agent_url,
                )
            else:
                if panel_credentials is not None:
                    skeleton = _credentials_to_skeleton_dict(panel_credentials)
                    if skeleton:
                        entry["auth"] = skeleton
        elif server_def and server_def.auth:
            entry["auth"] = _auth_config_to_dict(server_def.auth)

        servers[name] = entry
        existing_urls.add(agent_url)
        added += 1

    if added:
        data["servers"] = servers
        _write_servers_toml(path, data)

    return added
