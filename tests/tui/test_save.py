"""Tests for saving TUI connections back to workspace config."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import cast

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.cli.server import _read_toml
from a2a_handler.servers import ServerAuthConfig, ServerDefinition, ServerSource
from a2a_handler.tui.server.save import save_connections_to_workspace


def _fake_server_tab(
    *,
    agent_url: str,
    card_name: str,
    connected_server_def: ServerDefinition | None = None,
    panel_credentials: AuthCredentials | None = None,
):
    messages_panel = SimpleNamespace(get_auth_credentials=lambda: panel_credentials)
    server_view = SimpleNamespace(messages_panel=lambda: messages_panel)
    return SimpleNamespace(
        current_agent_url=agent_url,
        current_agent_card=SimpleNamespace(name=card_name),
        state=SimpleNamespace(connected_server_def=connected_server_def),
        _try_get_server_view=lambda: (
            server_view if panel_credentials is not None else None
        ),
    )


def _read_saved_server(path, name: str) -> dict[str, object]:
    data = _read_toml(path)
    servers = cast(dict[str, object], data["servers"])
    return cast(dict[str, object], servers[name])


def test_save_connections_to_workspace_preserves_oauth2_server_auth(
    tmp_path, monkeypatch
) -> None:
    """Configured OAuth2 server metadata should be saved without secret values."""
    config_path = tmp_path / ".handler" / "servers.toml"
    server_module = importlib.import_module("a2a_handler.cli.server")
    monkeypatch.setattr(
        server_module,
        "_resolve_servers_path",
        lambda use_repository: config_path,
    )

    server_def = ServerDefinition(
        server_id="repository:oauth",
        source=ServerSource.REPOSITORY,
        name="oauth",
        agent_url="https://oauth.example.com",
        auth=ServerAuthConfig(
            auth_type=AuthType.OAUTH2,
            token_url="https://oauth.example.com/token",
            client_id_env="CLIENT_ID",
            client_secret_env="CLIENT_SECRET",
            scopes=["read"],
        ),
        origin_label="Repository",
    )
    server_tab = _fake_server_tab(
        agent_url="https://oauth.example.com",
        card_name="OAuth Agent",
        connected_server_def=server_def,
    )

    assert save_connections_to_workspace([server_tab]) == 1

    saved = _read_saved_server(config_path, "oauth_agent")
    auth = cast(dict[str, object], saved["auth"])

    assert auth["type"] == "oauth2"
    assert auth["token_url"] == "https://oauth.example.com/token"
    assert auth["client_id_env"] == "CLIENT_ID"
    assert auth["client_secret_env"] == "CLIENT_SECRET"
    assert auth["scopes"] == ["read"]
    assert "client_id" not in auth
    assert "client_secret" not in auth
    assert "value" not in auth


def test_save_connections_to_workspace_uses_mtls_panel_skeleton(
    tmp_path, monkeypatch
) -> None:
    """Manual mTLS connections should save file-path metadata, not raw secrets."""
    config_path = tmp_path / ".handler" / "servers.toml"
    server_module = importlib.import_module("a2a_handler.cli.server")
    monkeypatch.setattr(
        server_module,
        "_resolve_servers_path",
        lambda use_repository: config_path,
    )

    panel_credentials = AuthCredentials(
        auth_type=AuthType.MTLS,
        cert_path="/secure/client.crt",
        key_path="/secure/client.key",
        ca_cert_path="/secure/ca.crt",
    )
    server_tab = _fake_server_tab(
        agent_url="https://mtls.example.com",
        card_name="mTLS Agent",
        panel_credentials=panel_credentials,
    )

    assert save_connections_to_workspace([server_tab]) == 1

    saved = _read_saved_server(config_path, "mtls_agent")
    auth = cast(dict[str, object], saved["auth"])

    assert auth == {
        "type": "mtls",
        "cert": "/secure/client.crt",
        "key": "/secure/client.key",
        "ca_cert": "/secure/ca.crt",
    }
