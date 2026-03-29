"""Tests for the workspace-based TUI shell."""

from collections.abc import Generator
from unittest.mock import AsyncMock, Mock, patch

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Input, Select, Static, Tab, Tabs

from a2a_handler.auth import AuthType, create_api_key_auth, create_bearer_auth
from a2a_handler.profiles import ConnectionProfile, ProfileAuthConfig
from a2a_handler.tui import HandlerTUI
from a2a_handler.tui.components import TabbedMessagesPanel
from a2a_handler.tui.workspace import (
    RemoteConnectView,
    RemoteLiveView,
    RemoteWorkspace,
    WorkspaceTabs,
)


@pytest.fixture(autouse=True)
def patch_workspace_sources() -> Generator[None, None, None]:
    """Keep TUI tests isolated from user profile and session files."""
    session_store = Mock()
    session_store.list_all.return_value = []

    with (
        patch("a2a_handler.tui.workspace.load_all_profiles", return_value={}),
        patch(
            "a2a_handler.tui.workspace.get_session_store", return_value=session_store
        ),
        patch("a2a_handler.tui.workspace.get_credentials", return_value=None),
    ):
        yield


@pytest.mark.asyncio
async def test_app_starts_with_workspace_shell_and_initial_remote() -> None:
    """Startup should create the workspace shell and one connect-stage remote."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace_tabs = app.query_one(WorkspaceTabs)
        workspace = workspace_tabs.get_active_workspace()

        assert workspace is not None
        assert not workspace.is_connected
        connect_view = workspace.query_one(RemoteConnectView)

        assert connect_view
        assert workspace.region.height > 5
        assert connect_view.region.height > 5
        assert connect_view.query_one("#connect-scroll", VerticalScroll)


def test_workspace_shell_does_not_hijack_tab_navigation() -> None:
    """Workspace switching should not steal the Tab key from form controls."""
    assert all(binding.key != "tab" for binding in WorkspaceTabs.BINDINGS)
    assert all(binding.key != "shift+tab" for binding in WorkspaceTabs.BINDINGS)


@pytest.mark.asyncio
async def test_initial_bearer_token_seeds_first_workspace_connect_view() -> None:
    """The first workspace should inherit an initial bearer token override."""
    app = HandlerTUI(initial_bearer_token="test-token")

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace = app.query_one(WorkspaceTabs).get_active_workspace()
        assert workspace is not None

        credentials = workspace.query_one(RemoteConnectView).get_auth_credentials()

        assert credentials is not None
        assert credentials.auth_type == AuthType.BEARER
        assert credentials.value == "test-token"


@pytest.mark.asyncio
async def test_new_remote_button_adds_workspace_tab() -> None:
    """The shell should allow creating another remote workspace tab."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#new-workspace-btn")
        await pilot.pause()

        workspace_tabs = app.query_one(WorkspaceTabs)
        tabs = app.query_one("#workspace-tabs", Tabs)

        assert len(workspace_tabs.iter_workspaces()) == 2
        assert tabs.tab_count == 2


@pytest.mark.asyncio
async def test_saved_target_selection_syncs_auth_into_connect_view() -> None:
    """Selecting a saved target should prefill advanced auth in the connect view."""
    app = HandlerTUI()
    resolved_credentials = create_api_key_auth("saved-key", header_name="X-Test-Key")
    resolved_credentials.custom_headers = {"x-org": "acme"}

    with patch(
        "a2a_handler.tui.workspace.get_credentials", return_value=resolved_credentials
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(WorkspaceTabs).get_active_workspace()
            assert workspace is not None

            connect_view = workspace.query_one(RemoteConnectView)
            connect_view.set_connection_targets(
                profile_urls={},
                saved_urls=["https://saved.example.com"],
            )

            selector = connect_view.query_one("#connection-target", Select)
            selector.value = "saved:https://saved.example.com"
            await pilot.pause()

            credentials = connect_view.get_auth_credentials()

            assert credentials is not None
            assert credentials.auth_type == AuthType.API_KEY
            assert credentials.value == "saved-key"
            assert credentials.header_name == "X-Test-Key"
            assert credentials.custom_headers == {"x-org": "acme"}


@pytest.mark.asyncio
async def test_connect_transitions_workspace_to_live_view_and_updates_tab_title() -> (
    None
):
    """Successful connect should morph the same workspace into the live layout."""
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.workspace.build_http_client",
            return_value=new_http_client,
        ) as mock_build_http_client,
        patch("a2a_handler.tui.workspace.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(WorkspaceTabs).get_active_workspace()
            assert workspace is not None

            connect_view = workspace.query_one(RemoteConnectView)
            connect_view.query_one(
                "#agent-url", Input
            ).value = "https://agent.example.com"
            await workspace.handle_connect_button()
            await pilot.pause()

            assert workspace.is_connected
            assert workspace.current_agent_url == "https://agent.example.com"
            assert workspace.query_one(RemoteLiveView)

            live_view = workspace.query_one(RemoteLiveView)
            messages_panel = live_view.query_one(TabbedMessagesPanel)
            tabs = app.query_one("#workspace-tabs", Tabs)
            first_tab = tabs.query_one("#workspace-tab-1", Tab)

            assert first_tab.label_text == "Demo Agent"
            assert messages_panel
            mock_build_http_client.assert_called_once_with(credentials=None)
            mock_service_cls.assert_called_once_with(
                new_http_client,
                "https://agent.example.com",
                credentials=None,
            )


@pytest.mark.asyncio
async def test_connect_validates_agent_url_before_service_call() -> None:
    """Malformed URLs should be rejected from the connect view."""
    app = HandlerTUI()

    with patch("a2a_handler.tui.workspace.A2AService") as mock_service_cls:
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(WorkspaceTabs).get_active_workspace()
            assert workspace is not None

            connect_view = workspace.query_one(RemoteConnectView)
            connect_view.query_one("#agent-url", Input).value = "not-a-url"
            await workspace.handle_connect_button()
            await pilot.pause()

            status = connect_view.query_one("#connect-status", Static)

            assert "valid http(s) URL" in str(status.content)
            mock_service_cls.assert_not_called()


def test_resolve_connection_credentials_prefers_manual_auth() -> None:
    """Manual auth remains the first precedence level in a workspace."""
    workspace = RemoteWorkspace(workspace_id="workspace-test", title="Remote Test")
    manual = create_bearer_auth("manual-token")

    with patch("a2a_handler.tui.workspace.get_credentials") as mock_get_credentials:
        credentials, source, warning = workspace._resolve_connection_credentials(
            agent_url="https://agent.example.com",
            selected_profile_name=None,
            manual_credentials=manual,
        )

    assert credentials == manual
    assert source == "manual (Auth tab)"
    assert warning is None
    mock_get_credentials.assert_not_called()


def test_resolve_connection_credentials_uses_profile_auth() -> None:
    """Profile auth should win when manual auth is not provided."""
    workspace = RemoteWorkspace(workspace_id="workspace-test", title="Remote Test")
    workspace._profiles = {
        "staging": ConnectionProfile(
            name="staging",
            agent_url="https://staging.example.com",
            auth=ProfileAuthConfig(auth_type=AuthType.BEARER, value="profile-token"),
        )
    }
    profile_credentials = create_bearer_auth("profile-token")
    workspace._profile_credentials = {"staging": profile_credentials}
    workspace._profile_warnings = {}

    with patch("a2a_handler.tui.workspace.get_credentials", return_value=None):
        credentials, source, warning = workspace._resolve_connection_credentials(
            agent_url="https://staging.example.com",
            selected_profile_name="staging",
            manual_credentials=None,
        )

    assert credentials == profile_credentials
    assert source == "profile 'staging'"
    assert warning is None
