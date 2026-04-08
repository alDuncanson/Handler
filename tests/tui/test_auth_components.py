"""Tests for TUI auth and headers component round-tripping."""

import os

from textual.app import App, ComposeResult

import pytest

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_bearer_auth,
    create_oauth2_auth,
)
from a2a_handler.tui.components import TabbedMessagesPanel


class _MessagesPanelHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield TabbedMessagesPanel()


@pytest.mark.asyncio
async def test_messages_panel_round_trips_oauth2_credentials_and_headers() -> None:
    """Resolved OAuth2 defaults should survive a panel round-trip."""
    credentials = create_oauth2_auth(
        "https://auth.example.com/token",
        "client-id",
        "client-secret",
        scopes=["read", "write"],
    )
    credentials.custom_headers = {"X-Org": "acme", "X-User": "alice"}

    app = _MessagesPanelHarness()

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.set_auth_credentials(credentials)

        restored = panel.get_auth_credentials()

        assert restored is not None
        assert restored.auth_type == AuthType.OAUTH2
        assert restored.token_url == "https://auth.example.com/token"
        assert restored.client_id == "client-id"
        assert restored.client_secret == "client-secret"
        assert restored.scopes == ["read", "write"]
        assert restored.custom_headers == {"X-Org": "acme", "X-User": "alice"}


@pytest.mark.asyncio
async def test_messages_panel_clears_auth_and_headers() -> None:
    """Clearing panel credentials should reset both auth and custom headers."""
    app = _MessagesPanelHarness()

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        credentials = create_bearer_auth("secret-token")
        credentials.custom_headers = {"X-Trace-ID": "123"}

        panel.set_auth_credentials(credentials)
        panel.set_auth_credentials(None)

        assert panel.get_auth_credentials() is None


@pytest.mark.asyncio
async def test_messages_panel_round_trips_mtls_credentials(tmp_path) -> None:
    """Resolved mTLS defaults should survive a panel round-trip."""
    cert_path = tmp_path / "client.crt"
    key_path = tmp_path / "client.key"
    ca_path = tmp_path / "ca.crt"
    cert_path.write_text("cert")
    key_path.write_text("key")
    ca_path.write_text("ca")
    os.chmod(key_path, 0o600)

    credentials = AuthCredentials(
        auth_type=AuthType.MTLS,
        cert_path=str(cert_path),
        key_path=str(key_path),
        ca_cert_path=str(ca_path),
        custom_headers={"X-Client": "workstation"},
    )

    app = _MessagesPanelHarness()

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.set_auth_credentials(credentials)

        restored = panel.get_auth_credentials()

        assert restored is not None
        assert restored.auth_type == AuthType.MTLS
        assert restored.cert_path == str(cert_path)
        assert restored.key_path == str(key_path)
        assert restored.ca_cert_path == str(ca_path)
        assert restored.custom_headers == {"X-Client": "workstation"}
