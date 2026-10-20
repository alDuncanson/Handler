"""Tests for saving TUI connections back to workspace config."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import cast

from a2a_handler.auth import (
    create_basic_auth,
    create_oidc_auth,
    AuthCredentials,
    AuthType,
    create_api_key_auth,
    create_bearer_auth,
)
from a2a_handler.cli.server import _read_toml
from a2a_handler.servers import (
    ServerAuthConfig,
    ServerDefinition,
    ServerSource,
    inspect_servers_file,
)
from a2a_handler.tui.server.save import save_connections_to_workspace


def _fake_server_tab(
    *,
    agent_url: str,
    card_name: str,
    connected_server_def: ServerDefinition | None = None,
    panel_credentials: AuthCredentials | None = None,
    panel_available: bool = False,
):
    messages_panel = SimpleNamespace(get_auth_credentials=lambda: panel_credentials)
    server_view = SimpleNamespace(messages_panel=lambda: messages_panel)
    return SimpleNamespace(
        current_agent_url=agent_url,
        current_agent_card=SimpleNamespace(name=card_name),
        state=SimpleNamespace(connected_server_def=connected_server_def),
        _try_get_server_view=lambda: (
            server_view if panel_available or panel_credentials is not None else None
        ),
    )


def _read_saved_server(path, name: str) -> dict[str, object]:
    data = _read_toml(path)
    servers = cast(dict[str, object], data["servers"])
    return cast(dict[str, object], servers[name])


def _patch_servers_path(tmp_path, monkeypatch):
    config_path = tmp_path / ".handler" / "servers.toml"
    server_module = importlib.import_module("a2a_handler.cli.server")
    monkeypatch.setattr(
        server_module,
        "_resolve_servers_path",
        lambda use_repository: config_path,
    )
    return config_path


def test_save_connections_to_workspace_preserves_oauth2_server_auth(
    tmp_path, monkeypatch
) -> None:
    """Configured OAuth2 server metadata should be saved without secret values."""
    config_path = _patch_servers_path(tmp_path, monkeypatch)

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


def test_save_connections_to_workspace_prefers_live_panel_auth_over_server_def(
    tmp_path, monkeypatch
) -> None:
    """Live panel auth should win over stale connected server metadata."""
    config_path = _patch_servers_path(tmp_path, monkeypatch)

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
    panel_credentials = create_bearer_auth("runtime-secret")
    server_tab = _fake_server_tab(
        agent_url="https://oauth.example.com",
        card_name="OAuth Agent",
        connected_server_def=server_def,
        panel_credentials=panel_credentials,
    )

    assert save_connections_to_workspace([server_tab]) == 1

    saved = _read_saved_server(config_path, "oauth_agent")
    auth = cast(dict[str, object], saved["auth"])
    assert auth == {"type": "bearer", "env": "BEARER_TOKEN"}


def test_save_connections_to_workspace_uses_mtls_panel_skeleton(
    tmp_path, monkeypatch
) -> None:
    """Manual mTLS connections should save file-path metadata, not raw secrets."""
    config_path = _patch_servers_path(tmp_path, monkeypatch)

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


def test_save_connections_to_workspace_skips_duplicate_urls(
    tmp_path, monkeypatch
) -> None:
    """Already-saved agent URLs should not be duplicated in the workspace config."""
    config_path = _patch_servers_path(tmp_path, monkeypatch)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        '[servers.existing]\nurl = "https://duplicate.example.com"\n',
        encoding="utf-8",
    )

    duplicate = _fake_server_tab(
        agent_url="https://duplicate.example.com",
        card_name="Duplicate Agent",
    )
    fresh = _fake_server_tab(
        agent_url="https://fresh.example.com",
        card_name="Fresh Agent",
    )

    assert save_connections_to_workspace([duplicate, fresh]) == 1

    data = _read_toml(config_path)
    servers = cast(dict[str, object], data["servers"])
    assert set(servers) == {"existing", "fresh_agent"}


def test_save_connections_to_workspace_disambiguates_colliding_server_names(
    tmp_path, monkeypatch
) -> None:
    """Sanitized server names should remain unique when multiple cards collide."""
    config_path = _patch_servers_path(tmp_path, monkeypatch)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        '[servers.demo_agent]\nurl = "https://existing.example.com"\n',
        encoding="utf-8",
    )

    first = _fake_server_tab(
        agent_url="https://one.example.com",
        card_name="Demo Agent",
    )
    second = _fake_server_tab(
        agent_url="https://two.example.com",
        card_name="Demo Agent",
    )

    assert save_connections_to_workspace([first, second]) == 2

    data = _read_toml(config_path)
    servers = cast(dict[str, object], data["servers"])
    assert set(servers) == {"demo_agent", "demo_agent_2", "demo_agent_3"}
    assert (
        cast(dict[str, object], servers["demo_agent_2"])["url"]
        == "https://one.example.com"
    )
    assert (
        cast(dict[str, object], servers["demo_agent_3"])["url"]
        == "https://two.example.com"
    )


def test_save_connections_to_workspace_uses_bearer_panel_skeleton(
    tmp_path, monkeypatch
) -> None:
    """Manual bearer credentials should persist as a safe env var placeholder."""
    config_path = _patch_servers_path(tmp_path, monkeypatch)
    panel_credentials = create_bearer_auth("secret-token")
    server_tab = _fake_server_tab(
        agent_url="https://bearer.example.com",
        card_name="Bearer Agent",
        panel_credentials=panel_credentials,
    )

    assert save_connections_to_workspace([server_tab]) == 1

    saved = _read_saved_server(config_path, "bearer_agent")
    auth = cast(dict[str, object], saved["auth"])
    assert auth == {"type": "bearer", "env": "BEARER_TOKEN"}


def test_save_connections_to_workspace_uses_api_key_panel_skeleton(
    tmp_path, monkeypatch
) -> None:
    """Manual API key credentials should save the placeholder env and custom header."""
    config_path = _patch_servers_path(tmp_path, monkeypatch)
    panel_credentials = create_api_key_auth("secret-key", header_name="X-Handler-Key")
    server_tab = _fake_server_tab(
        agent_url="https://api-key.example.com",
        card_name="API Key Agent",
        panel_credentials=panel_credentials,
    )

    assert save_connections_to_workspace([server_tab]) == 1

    saved = _read_saved_server(config_path, "api_key_agent")
    auth = cast(dict[str, object], saved["auth"])
    assert auth == {
        "type": "api_key",
        "env": "API_KEY",
        "header": "X-Handler-Key",
    }


def _assert_saved_file_loads(config_path, expected_name: str) -> None:
    """The point of saving is to load again later; prove the entry is valid."""
    result = inspect_servers_file(config_path.parent, ServerSource.REPOSITORY)
    assert result.diagnostics == ()
    assert [server.name for server in result.servers] == [expected_name]


def test_save_connections_to_workspace_preserves_basic_server_auth(
    tmp_path, monkeypatch
) -> None:
    """A configured Basic server keeps its username; without it the saved
    entry cannot load (the loader requires one)."""
    config_path = _patch_servers_path(tmp_path, monkeypatch)
    server_def = ServerDefinition(
        server_id="repository:basic",
        source=ServerSource.REPOSITORY,
        name="basic",
        agent_url="https://basic.example.com",
        auth=ServerAuthConfig(
            auth_type=AuthType.BASIC, username="alice", env_var="BASIC_PW"
        ),
        origin_label="Repository",
    )
    server_tab = _fake_server_tab(
        agent_url="https://basic.example.com",
        card_name="Basic Agent",
        connected_server_def=server_def,
    )

    assert save_connections_to_workspace([server_tab]) == 1

    saved = _read_saved_server(config_path, "basic_agent")
    assert saved["auth"] == {"type": "basic", "username": "alice", "env": "BASIC_PW"}
    _assert_saved_file_loads(config_path, "basic_agent")


def test_save_connections_to_workspace_preserves_oidc_server_auth(
    tmp_path, monkeypatch
) -> None:
    config_path = _patch_servers_path(tmp_path, monkeypatch)
    server_def = ServerDefinition(
        server_id="repository:oidc",
        source=ServerSource.REPOSITORY,
        name="oidc",
        agent_url="https://oidc.example.com",
        auth=ServerAuthConfig(
            auth_type=AuthType.OIDC,
            issuer_url="https://idp.example.com",
            client_id_env="CLIENT_ID",
            client_secret_env="CLIENT_SECRET",
            scopes=["openid"],
        ),
        origin_label="Repository",
    )
    server_tab = _fake_server_tab(
        agent_url="https://oidc.example.com",
        card_name="OIDC Agent",
        connected_server_def=server_def,
    )

    assert save_connections_to_workspace([server_tab]) == 1

    saved = _read_saved_server(config_path, "oidc_agent")
    assert saved["auth"] == {
        "type": "oidc",
        "issuer_url": "https://idp.example.com",
        "client_id_env": "CLIENT_ID",
        "client_secret_env": "CLIENT_SECRET",
        "scopes": ["openid"],
    }
    _assert_saved_file_loads(config_path, "oidc_agent")


def test_save_connections_to_workspace_uses_basic_panel_skeleton(
    tmp_path, monkeypatch
) -> None:
    """Typed Basic credentials keep the username and hide the password
    behind a placeholder env var, instead of being dropped."""
    config_path = _patch_servers_path(tmp_path, monkeypatch)
    server_tab = _fake_server_tab(
        agent_url="https://basic.example.com",
        card_name="Basic Agent",
        panel_credentials=create_basic_auth("alice", "s3cret"),
    )

    assert save_connections_to_workspace([server_tab]) == 1

    saved = _read_saved_server(config_path, "basic_agent")
    assert saved["auth"] == {
        "type": "basic",
        "username": "alice",
        "env": "BASIC_PASSWORD",
    }
    assert "s3cret" not in config_path.read_text()
    _assert_saved_file_loads(config_path, "basic_agent")


def test_save_connections_to_workspace_uses_oidc_panel_skeleton(
    tmp_path, monkeypatch
) -> None:
    config_path = _patch_servers_path(tmp_path, monkeypatch)
    server_tab = _fake_server_tab(
        agent_url="https://oidc.example.com",
        card_name="OIDC Agent",
        panel_credentials=create_oidc_auth(
            "https://idp.example.com", "real-id", "real-secret", scopes=["openid"]
        ),
    )

    assert save_connections_to_workspace([server_tab]) == 1

    saved = _read_saved_server(config_path, "oidc_agent")
    assert saved["auth"] == {
        "type": "oidc",
        "issuer_url": "https://idp.example.com",
        "client_id_env": "CLIENT_ID",
        "client_secret_env": "CLIENT_SECRET",
        "scopes": ["openid"],
    }
    text = config_path.read_text()
    assert "real-id" not in text and "real-secret" not in text
    _assert_saved_file_loads(config_path, "oidc_agent")


def test_save_connections_to_workspace_keeps_static_headers(
    tmp_path, monkeypatch
) -> None:
    """Headers configured on the server, or typed into the Headers tab, are
    saved as a headers table and load back."""
    config_path = _patch_servers_path(tmp_path, monkeypatch)
    server_def = ServerDefinition(
        server_id="repository:remy",
        source=ServerSource.REPOSITORY,
        name="remy",
        agent_url="https://remy.example.com",
        origin_label="Repository",
        headers=(("X-Remy-User", "alice"),),
    )
    from_config = _fake_server_tab(
        agent_url="https://remy.example.com",
        card_name="Remy",
        connected_server_def=server_def,
    )
    typed = create_bearer_auth("tok")
    typed.custom_headers = {"X-Tenant": "acme"}
    from_panel = _fake_server_tab(
        agent_url="https://tenant.example.com",
        card_name="Tenant Agent",
        panel_credentials=typed,
    )

    assert save_connections_to_workspace([from_config, from_panel]) == 2

    assert _read_saved_server(config_path, "remy")["headers"] == {
        "X-Remy-User": "alice"
    }
    assert _read_saved_server(config_path, "tenant_agent")["headers"] == {
        "X-Tenant": "acme"
    }
    result = inspect_servers_file(config_path.parent, ServerSource.REPOSITORY)
    assert result.diagnostics == ()
    assert {s.name: s.headers for s in result.servers} == {
        "remy": (("X-Remy-User", "alice"),),
        "tenant_agent": (("X-Tenant", "acme"),),
    }
