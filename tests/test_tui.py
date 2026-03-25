"""Tests for the TUI application."""

from unittest.mock import AsyncMock, patch

import pytest
from a2a.types import AgentCard
from textual.widgets import Select

from a2a_handler.auth import (
    AuthType,
    create_api_key_auth,
    create_bearer_auth,
    create_mtls_auth,
)
from a2a_handler.profiles import ConnectionProfile, ProfileAuthConfig
from a2a_handler.tui import HandlerTUI
from a2a_handler.tui.components import TabbedMessagesPanel
from a2a_handler.tui.components.contact import ContactPanel


@pytest.mark.asyncio
async def test_app_startup():
    """Test that the app starts up and displays the initial state."""
    app = HandlerTUI()
    async with app.run_test() as _:
        assert app.query_one("#root-container")


@pytest.mark.asyncio
async def test_app_startup_with_initial_bearer_token():
    """Test startup preconfigures bearer token auth when provided."""
    app = HandlerTUI(initial_bearer_token="test-token")
    async with app.run_test() as _:
        messages_panel = app.query_one("#messages-container", TabbedMessagesPanel)
        credentials = messages_panel.get_auth_credentials()

        assert credentials is not None
        assert credentials.auth_type == AuthType.BEARER
        assert credentials.value == "test-token"


@pytest.mark.asyncio
async def test_connect_to_agent_uses_credentials_for_card_request():
    """Test connect flow applies auth credentials before fetching card."""
    app = HandlerTUI()
    old_http_client = AsyncMock()
    new_http_client = AsyncMock()
    app.http_client = old_http_client
    credentials = create_bearer_auth("test-token")
    mock_card = AsyncMock(spec=AgentCard)

    with (
        patch(
            "a2a_handler.tui.app.build_http_client", return_value=new_http_client
        ) as mock_build_http_client,
        patch("a2a_handler.tui.app.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        card = await app._connect_to_agent("https://agent.example.com", credentials)

        assert card is mock_card
        old_http_client.aclose.assert_awaited_once()
        mock_build_http_client.assert_called_once_with(credentials=credentials)
        assert app.http_client is new_http_client
        mock_service_cls.assert_called_once_with(
            new_http_client,
            "https://agent.example.com",
            credentials=credentials,
        )


def test_resolve_connection_credentials_prefers_manual_auth() -> None:
    """Manual auth from the Auth tab takes precedence over profile/saved state."""
    app = HandlerTUI()
    manual = create_bearer_auth("manual-token")

    with patch("a2a_handler.tui.app.get_credentials") as mock_get_credentials:
        credentials, source, warning = app._resolve_connection_credentials(
            agent_url="https://agent.example.com",
            selected_profile_name=None,
            manual_credentials=manual,
        )

    assert credentials == manual
    assert source == "manual (Auth tab)"
    assert warning is None
    mock_get_credentials.assert_not_called()


def test_resolve_connection_credentials_uses_profile_auth() -> None:
    """Profile auth is used when no manual auth is supplied."""
    app = HandlerTUI()
    app._profiles = {
        "staging": ConnectionProfile(
            name="staging",
            agent_url="https://staging.example.com",
            auth=ProfileAuthConfig(auth_type=AuthType.BEARER, value="profile-token"),
        )
    }
    profile_credentials = create_bearer_auth("profile-token")
    app._profile_credentials = {"staging": profile_credentials}
    app._profile_warnings = {}

    with patch("a2a_handler.tui.app.get_credentials", return_value=None):
        credentials, source, warning = app._resolve_connection_credentials(
            agent_url="https://staging.example.com",
            selected_profile_name="staging",
            manual_credentials=None,
        )

    assert credentials == profile_credentials
    assert source == "profile 'staging'"
    assert warning is None


def test_resolve_connection_credentials_falls_back_to_saved_when_profile_unavailable() -> (
    None
):
    """Saved URL credentials are used when profile auth source cannot resolve."""
    app = HandlerTUI()
    app._profiles = {
        "prod": ConnectionProfile(
            name="prod",
            agent_url="https://api.example.com",
            auth=ProfileAuthConfig(auth_type=AuthType.BEARER, env_var="MISSING_TOKEN"),
        )
    }
    app._profile_credentials = {}
    app._profile_warnings = {"prod": "missing env var"}
    saved_credentials = create_api_key_auth("saved-key")

    with patch("a2a_handler.tui.app.get_credentials", return_value=saved_credentials):
        credentials, source, warning = app._resolve_connection_credentials(
            agent_url="https://api.example.com",
            selected_profile_name="prod",
            manual_credentials=None,
        )

    assert credentials == saved_credentials
    assert source == "saved (profile 'prod' unavailable)"
    assert warning == "missing env var"


def test_resolve_connection_credentials_uses_saved_for_custom_url() -> None:
    """Saved credentials are used for non-profile URL selections."""
    app = HandlerTUI()
    app._profiles = {}
    app._profile_credentials = {}
    app._profile_warnings = {}
    saved_credentials = create_bearer_auth("saved-token")

    with patch("a2a_handler.tui.app.get_credentials", return_value=saved_credentials):
        credentials, source, warning = app._resolve_connection_credentials(
            agent_url="https://custom.example.com",
            selected_profile_name=None,
            manual_credentials=None,
        )

    assert credentials == saved_credentials
    assert source == "saved"
    assert warning is None


def test_resolve_connection_credentials_reports_profile_url_mismatch() -> None:
    """Selected profile is ignored when URL input differs from profile URL."""
    app = HandlerTUI()
    app._profiles = {
        "prod": ConnectionProfile(
            name="prod",
            agent_url="https://api.example.com",
            auth=ProfileAuthConfig(auth_type=AuthType.BEARER, value="profile-token"),
        )
    }
    app._profile_credentials = {"prod": create_bearer_auth("profile-token")}
    app._profile_warnings = {}

    with patch("a2a_handler.tui.app.get_credentials", return_value=None):
        credentials, source, warning = app._resolve_connection_credentials(
            agent_url="https://custom.example.com",
            selected_profile_name="prod",
            manual_credentials=None,
        )

    assert credentials is None
    assert source == "none (selected profile 'prod' URL differs)"
    assert warning is None


@pytest.mark.asyncio
async def test_profile_selection_syncs_api_key_into_auth_tab() -> None:
    """Selecting a saved/profile URL syncs resolved auth into the Auth tab fields."""
    app = HandlerTUI()
    app._profiles = {}
    app._profile_credentials = {}
    app._profile_warnings = {}

    resolved_credentials = create_api_key_auth("saved-key", header_name="X-Test-Key")
    resolved_credentials.custom_headers = {
        "x-org": "acme",
        "x-user-id": "me@example.com",
    }

    with patch(
        "a2a_handler.tui.app.get_credentials", return_value=resolved_credentials
    ):
        async with app.run_test() as _:
            contact_panel = app.query_one("#contact-container", ContactPanel)
            contact_panel.set_connection_targets(
                profile_urls={},
                saved_urls=["https://saved.example.com"],
            )

            selector = app.query_one("#connection-target", Select)
            selector.value = "saved:https://saved.example.com"

            messages_panel = app.query_one("#messages-container", TabbedMessagesPanel)
            credentials = messages_panel.get_auth_credentials()

            assert credentials is not None
            assert credentials.auth_type == AuthType.API_KEY
            assert credentials.value == "saved-key"
            assert credentials.header_name == "X-Test-Key"
            assert credentials.custom_headers == resolved_credentials.custom_headers


@pytest.mark.asyncio
async def test_profile_selection_syncs_mtls_into_auth_tab(tmp_path) -> None:
    """Selecting a saved/profile URL syncs mTLS cert paths into the Auth tab."""
    app = HandlerTUI()

    cert_path = tmp_path / "client.crt"
    key_path = tmp_path / "client.key"
    ca_cert_path = tmp_path / "ca.crt"
    cert_path.write_text("cert")
    key_path.write_text("key")
    ca_cert_path.write_text("ca")

    resolved_credentials = create_mtls_auth(
        str(cert_path),
        str(key_path),
        str(ca_cert_path),
    )
    resolved_credentials.custom_headers = {"x-org": "acme"}

    with patch(
        "a2a_handler.tui.app.get_credentials", return_value=resolved_credentials
    ):
        async with app.run_test() as _:
            contact_panel = app.query_one("#contact-container", ContactPanel)
            contact_panel.set_connection_targets(
                profile_urls={},
                saved_urls=["https://mtls.example.com"],
            )

            selector = app.query_one("#connection-target", Select)
            selector.value = "saved:https://mtls.example.com"

            messages_panel = app.query_one("#messages-container", TabbedMessagesPanel)
            credentials = messages_panel.get_auth_credentials()

            assert credentials is not None
            assert credentials.auth_type == AuthType.MTLS
            assert credentials.cert_path == str(cert_path)
            assert credentials.key_path == str(key_path)
            assert credentials.ca_cert_path == str(ca_cert_path)
            assert credentials.custom_headers == {"x-org": "acme"}


@pytest.mark.asyncio
async def test_saved_target_selection_syncs_auth_without_manual_edit() -> None:
    """Selecting a saved target should populate auth even without URL typing."""
    app = HandlerTUI()

    with patch(
        "a2a_handler.tui.app.get_credentials",
        return_value=create_api_key_auth("saved-key", header_name="X-Saved"),
    ):
        async with app.run_test() as _:
            contact_panel = app.query_one("#contact-container", ContactPanel)
            contact_panel.set_connection_targets(
                profile_urls={},
                saved_urls=["https://saved.example.com"],
            )

            selector = app.query_one("#connection-target", Select)
            selector.value = "saved:https://saved.example.com"

            messages_panel = app.query_one("#messages-container", TabbedMessagesPanel)
            credentials = messages_panel.get_auth_credentials()

            assert credentials is not None
            assert credentials.auth_type == AuthType.API_KEY
            assert credentials.value == "saved-key"
            assert credentials.header_name == "X-Saved"


@pytest.mark.asyncio
async def test_profile_selection_does_not_override_manual_auth() -> None:
    """Manual edits in the Auth tab remain authoritative until target changes."""
    app = HandlerTUI()

    with patch(
        "a2a_handler.tui.app.get_credentials", return_value=create_api_key_auth("saved")
    ):
        async with app.run_test() as _:
            messages_panel = app.query_one("#messages-container", TabbedMessagesPanel)
            messages_panel.set_bearer_token("manual-token")

            credentials, source, warning = app._resolve_connection_credentials(
                agent_url="https://agent.example.com",
                selected_profile_name=None,
                manual_credentials=messages_panel.get_auth_credentials(),
                manual_override=True,
            )

            assert credentials is not None
            assert credentials.auth_type == AuthType.BEARER
            assert credentials.value == "manual-token"
            assert source == "manual (Auth tab)"
            assert warning is None


def test_resolve_connection_credentials_manual_none_disables_fallback() -> None:
    """Manual override with no credentials prevents profile/saved fallback usage."""
    app = HandlerTUI()
    app._profiles = {
        "prod": ConnectionProfile(
            name="prod",
            agent_url="https://api.example.com",
            auth=ProfileAuthConfig(auth_type=AuthType.BEARER, value="profile-token"),
        )
    }
    app._profile_credentials = {"prod": create_bearer_auth("profile-token")}
    app._profile_warnings = {}

    credentials, source, warning = app._resolve_connection_credentials(
        agent_url="https://api.example.com",
        selected_profile_name="prod",
        manual_credentials=None,
        manual_override=True,
    )

    assert credentials is None
    assert source == "manual (none)"
    assert warning is None
