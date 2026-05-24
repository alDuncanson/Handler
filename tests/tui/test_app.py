"""Tests for the server-based TUI shell."""

import asyncio
import subprocess
from collections.abc import Generator
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from a2a.client.errors import A2AClientJSONRPCError
from a2a.types import (
    JSONRPCError,
    JSONRPCErrorResponse,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
)
from textual.app import App as TextualApp, SystemCommand
from textual.widgets import Button, HelpPanel, Input, Select, Static, Tab, Tabs

from a2a_handler.auth import AuthType, create_bearer_auth
from a2a_handler.servers import (
    DEFAULT_HANDLER_AGENT_URL,
    ServerAuthConfig,
    ServerCatalog,
    ServerDefinition,
    ServerSource,
    default_handler_agent_server,
)
from a2a_handler.session import AgentSession
from a2a_handler.tui import HandlerTUI
from a2a_handler.tui.app import HandlerTUI as HandlerTUIApplication
from a2a_handler.tui.components import AgentCardPanel, TabbedMessagesPanel
from a2a_handler.tui.server.tabs import ServerTabs
from a2a_handler.tui.server.views import ConnectionBar, ServerView


def _chat_texts(messages_panel: TabbedMessagesPanel) -> list[str]:
    chat = messages_panel.query_one("#chat")
    return [str(getattr(widget, "content", "")) for widget in chat.children]


def _make_server(
    *,
    source: ServerSource,
    name: str,
    agent_url: str,
    auth: ServerAuthConfig | None = None,
) -> ServerDefinition:
    return ServerDefinition(
        server_id=f"{source.value}:{name}",
        source=source,
        name=name,
        agent_url=agent_url,
        auth=auth,
        origin_label=source.value.capitalize(),
    )


def _missing_task_error(task_id: str) -> A2AClientJSONRPCError:
    return A2AClientJSONRPCError(
        JSONRPCErrorResponse(
            error=JSONRPCError(
                code=-32001,
                data=None,
                message=f"Task {task_id} was specified but does not exist",
            ),
            id="request-1",
            jsonrpc="2.0",
        )
    )


def _completed_task_error(task_id: str) -> A2AClientJSONRPCError:
    return A2AClientJSONRPCError(
        JSONRPCErrorResponse(
            error=JSONRPCError(
                code=-32002,
                data=None,
                message=(
                    f"Messages sent to task {task_id} in a terminal state "
                    "cannot accept further messages"
                ),
            ),
            id="request-2",
            jsonrpc="2.0",
        )
    )


@pytest.fixture(autouse=True)
def patch_server_sources() -> Generator[Mock, None, None]:
    """Keep TUI tests isolated from user server and session files."""
    session_store = Mock()
    session_store.find.return_value = None
    session_store.list_all.return_value = []
    session_store.recent_agent_urls.return_value = []

    empty_catalog = ServerCatalog()
    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=empty_catalog,
        ),
        patch(
            "a2a_handler.tui.server.tabs.load_server_catalog",
            return_value=empty_catalog,
        ),
        patch(
            "a2a_handler.tui.server.tab.get_session_store",
            return_value=session_store,
        ),
    ):
        yield session_store


@pytest.mark.asyncio
async def test_app_starts_with_server_shell_and_initial_server() -> None:
    """Startup should create one unified server with the connection bar ready."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace_tabs = app.query_one(ServerTabs)
        workspace = workspace_tabs.get_active_server()

        assert workspace is not None
        assert not workspace.is_connected
        connect_view = workspace.query_one(ConnectionBar)
        live_view = workspace.query_one(ServerView)

        assert connect_view
        assert live_view
        assert workspace.region.height > 5
        assert connect_view.query_one("#server-bar")
        assert len(list(live_view.query("#server-summary"))) == 0
        assert connect_view.query_one("#connect-shell").border_subtitle == "Server"
        assert connect_view.query_one("#connect-shell").border_title is None

        status = connect_view.query_one("#badge-status", Static)
        assert "Disconnected" in str(status.content)
        assert status.has_class("badge-muted")


def test_server_shell_does_not_hijack_tab_navigation() -> None:
    """Server switching should not steal the Tab key from form controls."""
    assert all(binding.key != "tab" for binding in ServerTabs.BINDINGS)
    assert all(binding.key != "shift+tab" for binding in ServerTabs.BINDINGS)


def test_app_uses_ctrl_c_for_quit_binding() -> None:
    """The app should advertise ctrl+c as the quit shortcut."""
    assert any(binding.key == "ctrl+c" for binding in HandlerTUIApplication.BINDINGS)
    assert all(binding.key != "ctrl+q" for binding in HandlerTUIApplication.BINDINGS)


def test_app_advertises_server_hotkeys() -> None:
    """Server shortcuts should be available at the app level."""
    bindings_by_key = {
        binding.key: binding.action for binding in HandlerTUIApplication.BINDINGS
    }

    assert bindings_by_key["ctrl+n"] == "new_server"
    assert bindings_by_key["ctrl+b"] == "previous_server"
    assert bindings_by_key["ctrl+t"] == "next_server"


@pytest.mark.asyncio
async def test_footer_shows_global_help_and_version() -> None:
    """The footer should stay compact while surfacing app-level help."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.screen.active_bindings["ctrl+c"].binding.action == "quit"

        footer = app.query_one("#app-footer-bindings", Static)
        footer_labels = str(footer.content)

        assert "Ctrl+C Quit" in footer_labels
        assert "Ctrl+P Command Palette" in footer_labels
        assert "? Keybindings" in footer_labels
        assert "Ctrl+B" not in footer_labels
        assert "Ctrl+T" not in footer_labels
        assert "Ctrl+N" not in footer_labels

        version = app.query_one("#app-version", Static)
        assert str(version.content) == "v0.1.21"


@pytest.mark.asyncio
async def test_keybindings_shortcut_toggles_help_panel() -> None:
    """The keybindings shortcut should open and close the help panel."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()
        assert not app.screen.query(HelpPanel)

        await pilot.press("?")
        await pilot.pause()
        assert app.screen.query(HelpPanel)

        await pilot.press("?")
        await pilot.pause()
        assert not app.screen.query(HelpPanel)


@pytest.mark.asyncio
async def test_command_palette_is_centered_instead_of_full_width() -> None:
    """The command palette should render as a centered dialog, not a full-width sheet."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+p")
        await pilot.pause(1)

        palette = app.screen_stack[-1]
        input_row = palette.query_one("#--input")
        input_widget = palette.query_one("#--input Input", Input)
        command_list = palette.query_one("CommandList")
        search_icon = palette.query_one("SearchIcon")

        assert command_list.region.width < app.screen.region.width
        assert command_list.region.x > 0
        assert input_widget.styles.border_left[0] == ""
        assert command_list.styles.border_left[0] == ""
        assert input_row.styles.padding.left == 1
        assert input_row.styles.padding.right == 1
        assert input_row.styles.padding.top == 1
        assert input_row.region.height >= 3
        assert input_widget.region.y == input_row.region.y + 1
        assert search_icon.styles.display == "none"
        assert input_row.styles.content_align_vertical == "middle"


@pytest.mark.asyncio
async def test_system_commands_filter_builtin_layout_entries_and_offer_connect_actions(
    monkeypatch: pytest.MonkeyPatch,
    patch_server_sources: Mock,
) -> None:
    """App commands should hide builtin maximize/minimize while exposing connect flows."""
    monkeypatch.setattr(
        TextualApp,
        "get_system_commands",
        lambda self, screen: iter(
            [
                SystemCommand("Maximize", "builtin", lambda: None),
                SystemCommand("Minimize", "builtin", lambda: None),
                SystemCommand("Inspect Layout", "builtin", lambda: None),
            ]
        ),
    )
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        commands = list(app.get_system_commands(app.screen))
        titles = [command.title for command in commands]

        assert "Maximize" not in titles
        assert "Minimize" not in titles
        assert "Inspect Layout" in titles
        assert "Connect" in titles
        assert "Resume Saved Context" not in titles
        assert "Git Add Servers" not in titles


@pytest.mark.asyncio
async def test_system_commands_include_save_close_and_switch_for_multi_server_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System commands should reflect multi-server state and allow switching tabs."""
    monkeypatch.setattr(
        TextualApp,
        "get_system_commands",
        lambda self, screen: iter(()),
    )
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#connect-btn")
            await pilot.pause()
            await app.action_new_server()
            await pilot.pause()

            commands = list(app.get_system_commands(app.screen))
            titles = [command.title for command in commands]

            assert "Connect" in titles
            assert "Resume Saved Context" not in titles
            assert "Start Fresh Conversation" not in titles
            assert "Rename Saved Workspace Server" in titles
            assert "Remove Saved Workspace Server" in titles
            assert "Close Server 2" in titles
            assert "Git Add Servers" in titles

            connected_server = app.query_one(ServerTabs).query_one("#server-1")
            connect_button = connected_server.query_one("#connect-btn", Button)
            assert str(connect_button.label) == "RECONNECT"
            assert connect_button.has_class("reconnect")

            switch_command = next(
                command
                for command in commands
                if command.title.startswith("Switch to ")
            )
            switch_command.callback()
            await pilot.pause()

            tabs = app.query_one("#server-tabs", Tabs)
            assert tabs.active == "server-tab-1"


@pytest.mark.asyncio
async def test_system_commands_include_reconnect_and_forget_saved_session(
    monkeypatch: pytest.MonkeyPatch,
    patch_server_sources: Mock,
) -> None:
    """Connected servers with saved context should offer reconnect and forget actions."""
    monkeypatch.setattr(
        TextualApp,
        "get_system_commands",
        lambda self, screen: iter(()),
    )
    saved_session = AgentSession(
        agent_url="https://agent.example.com",
        context_id="ctx-saved-123456",
        task_id="task-saved-654321",
        last_used_at="2024-01-02T03:04:05+00:00",
    )
    patch_server_sources.find.side_effect = (
        lambda agent_url: saved_session
        if agent_url == "https://agent.example.com"
        else None
    )
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#connect-btn")
            await pilot.pause()

            commands = list(app.get_system_commands(app.screen))
            titles = [command.title for command in commands]

            assert "Connect" not in titles
            assert "Reconnect" in titles
            assert "Start Fresh Conversation" in titles
            assert "Forget Saved Session" in titles


@pytest.mark.asyncio
async def test_check_action_only_enables_maximize_for_maximizable_panels() -> None:
    """Maximize should only be advertised when focus is inside activity or card panels."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.check_action("toggle_maximize", ()) is False

        workspace = app.query_one(ServerTabs).get_active_server()
        assert workspace is not None

        workspace.query_one(AgentCardPanel).focus()
        await pilot.pause()
        assert app.check_action("toggle_maximize", ()) is True

        workspace.query_one(TabbedMessagesPanel).focus()
        await pilot.pause()
        assert app.check_action("toggle_maximize", ()) is True

        workspace.query_one("#manual-agent-url", Input).focus()
        await pilot.pause()
        assert app.check_action("toggle_maximize", ()) is False


@pytest.mark.asyncio
async def test_action_toggle_maximize_maximizes_then_restores_focused_panel() -> None:
    """The maximize action should target the focused activity panel and then restore it."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace = app.query_one(ServerTabs).get_active_server()
        assert workspace is not None

        messages_panel = workspace.query_one(TabbedMessagesPanel)
        messages_panel.focus()
        await pilot.pause()

        maximize_mock = Mock()
        minimize_mock = Mock()
        app.screen.maximize = maximize_mock  # type: ignore[method-assign]
        app.screen.minimize = minimize_mock  # type: ignore[method-assign]

        app.action_toggle_maximize()

        maximize_mock.assert_called_once_with(messages_panel)
        assert app._is_maximized is True

        app.action_toggle_maximize()

        minimize_mock.assert_called_once_with()
        assert app._is_maximized is False


@pytest.mark.asyncio
async def test_initial_bearer_token_seeds_first_server_auth_panel() -> None:
    """The first server should inherit an explicit auth in the panel."""
    app = HandlerTUI(initial_bearer_token="test-token")

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace = app.query_one(ServerTabs).get_active_server()
        assert workspace is not None

        server_view = workspace.query_one(ServerView)
        credentials = server_view.messages_panel().get_auth_credentials()

        assert credentials is not None
        assert credentials.auth_type == AuthType.BEARER
        assert credentials.value == "test-token"


@pytest.mark.asyncio
async def test_auto_connected_oauth2_server_populates_auth_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicitly auto-connected OAuth2 servers should sync credentials into Auth."""
    monkeypatch.setenv("CLIENT_ID", "resolved-client-id")
    monkeypatch.setenv("CLIENT_SECRET", "resolved-client-secret")

    plain_server = _make_server(
        source=ServerSource.REPOSITORY,
        name="plain",
        agent_url="https://plain.example.com",
    )
    oauth_server = _make_server(
        source=ServerSource.REPOSITORY,
        name="oauth",
        agent_url="https://oauth.example.com",
        auth=ServerAuthConfig(
            auth_type=AuthType.OAUTH2,
            token_url="https://oauth.example.com/token",
            client_id_env="CLIENT_ID",
            client_secret_env="CLIENT_SECRET",
            scopes=["read", "write"],
        ),
    )

    app = HandlerTUI(connect_servers=("plain", "oauth"))
    connected_credentials: dict[str, object | None] = {}

    def build_http_client_side_effect(*args: object, **kwargs: object) -> AsyncMock:
        return AsyncMock()

    def service_side_effect(
        http_client: AsyncMock,
        agent_url: str,
        credentials: object | None = None,
    ) -> AsyncMock:
        connected_credentials[agent_url] = credentials
        service = AsyncMock()
        mock_card = Mock()
        mock_card.name = f"Agent for {agent_url}"
        mock_card.protocol_version = None
        mock_card.version = None
        mock_card.model_dump.return_value = {"name": mock_card.name}
        service.get_card.return_value = mock_card
        return service

    with (
        patch(
            "a2a_handler.tui.server.tabs.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(plain_server, oauth_server)),
        ),
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(plain_server, oauth_server)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            side_effect=build_http_client_side_effect,
        ),
        patch("a2a_handler.tui.server.tab.A2AService", side_effect=service_side_effect),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            servers = app.query_one(ServerTabs).iter_servers()
            oauth_tab = next(
                server
                for server in servers
                if server.current_agent_url == "https://oauth.example.com"
            )

            credentials = (
                oauth_tab.query_one(ServerView).messages_panel().get_auth_credentials()
            )

            assert oauth_tab.is_connected
            assert credentials is not None
            assert credentials.auth_type == AuthType.OAUTH2
            assert credentials.token_url == "https://oauth.example.com/token"
            assert credentials.client_id == "resolved-client-id"
            assert credentials.client_secret == "resolved-client-secret"
            assert credentials.scopes == ["read", "write"]

            connected_oauth = connected_credentials["https://oauth.example.com"]
            assert connected_oauth is not None
            assert getattr(connected_oauth, "auth_type") == AuthType.OAUTH2


@pytest.mark.asyncio
async def test_new_server_button_adds_server_tab() -> None:
    """The shell should allow creating another server tab."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#new-server-btn")
        await pilot.pause()

        server_tabs = app.query_one(ServerTabs)
        tabs = app.query_one("#server-tabs", Tabs)

        assert len(server_tabs.iter_servers()) == 2
        assert tabs.tab_count == 2


@pytest.mark.asyncio
async def test_server_hotkeys_create_and_switch_servers() -> None:
    """Global shortcuts should add and cycle server tabs."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()

        server_tabs = app.query_one(ServerTabs)
        tabs = app.query_one("#server-tabs", Tabs)
        active_server = server_tabs.get_active_server()

        assert len(server_tabs.iter_servers()) == 2
        assert tabs.active == "server-tab-2"
        assert active_server is not None

        active_server.query_one("#server-select", Select).focus()
        await pilot.press("ctrl+b")
        await pilot.pause()

        assert tabs.active == "server-tab-1"

        active_server = server_tabs.get_active_server()
        assert active_server is not None

        active_server.query_one("#server-select", Select).focus()
        await pilot.press("ctrl+t")
        await pilot.pause()

        assert tabs.active == "server-tab-2"


@pytest.mark.asyncio
async def test_repository_connection_tab_is_default_and_selects_first_connection() -> (
    None
):
    """Repository connections should be the primary default tab and selection."""
    app = HandlerTUI()
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="staging",
        agent_url="https://staging.example.com",
    )

    with patch(
        "a2a_handler.tui.server.tab.load_server_catalog",
        return_value=ServerCatalog(repository_servers=(repo_connection,)),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            connect_view = workspace.query_one(ConnectionBar)

            assert connect_view.get_selected_server() == repo_connection
            assert connect_view.get_url() == "https://staging.example.com"


@pytest.mark.asyncio
async def test_repository_connections_do_not_auto_connect_on_startup() -> None:
    """Repository servers should be selectable by default but never auto-connect."""
    app = HandlerTUI()
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="staging",
        agent_url="https://staging.example.com",
    )

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch("a2a_handler.tui.server.tab.build_http_client") as mock_http_client,
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None
            assert workspace.is_connected is False

    mock_http_client.assert_not_called()
    mock_service_cls.assert_not_called()


@pytest.mark.asyncio
async def test_recent_connections_are_loaded_from_session_recency(
    patch_server_sources: Mock,
) -> None:
    """Recent sessions should appear in the picker, even for configured URLs."""
    patch_server_sources.list_all.return_value = [
        AgentSession(
            agent_url="https://recent.example.com",
            context_id="ctx-saved-123456",
            task_id="task-saved-654321",
            last_used_at="2024-01-02T03:04:05+00:00",
        )
    ]
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="recent",
        agent_url="https://recent.example.com",
    )
    app = HandlerTUI()

    with patch(
        "a2a_handler.tui.server.tab.load_server_catalog",
        return_value=ServerCatalog(repository_servers=(repo_connection,)),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            connect_view = workspace.query_one(ConnectionBar)
            server_select = connect_view.query_one("#server-select", Select)
            server_select.value = "recent:https://recent.example.com"
            await pilot.pause()

            selected = connect_view.get_selected_server()
            assert selected is not None
            assert selected.source == ServerSource.RECENT
            assert selected.agent_url == "https://recent.example.com"
            assert selected.label == "recent"


@pytest.mark.asyncio
async def test_picker_labels_show_source_and_resume_intent(
    patch_server_sources: Mock,
) -> None:
    """Picker labels should distinguish fresh server entries from resumable recent ones."""
    patch_server_sources.list_all.return_value = [
        AgentSession(
            agent_url="https://echo.example.com",
            context_id="ctx-saved-123456",
            task_id="task-saved-654321",
            last_used_at="2024-01-02T03:04:05+00:00",
        )
    ]
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="echo_agent",
        agent_url="https://echo.example.com",
    )
    global_connection = _make_server(
        source=ServerSource.GLOBAL,
        name="dev_agent",
        agent_url="https://dev.example.com",
    )
    app = HandlerTUI()

    with patch(
        "a2a_handler.tui.server.tab.load_server_catalog",
        return_value=ServerCatalog(
            repository_servers=(repo_connection,),
            global_servers=(global_connection,),
        ),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            select = workspace.query_one("#server-select", Select)
            labels = [
                prompt
                for prompt, value in select._options
                if value is not Select.BLANK and isinstance(prompt, str)
            ]

            assert labels == [
                "Repository: echo_agent",
                "User: dev_agent",
                "Recent: echo_agent (resume)",
                "URL...",
            ]


@pytest.mark.asyncio
async def test_default_handler_agent_appears_in_picker() -> None:
    """The built-in Handler agent should be selectable like a global server."""
    app = HandlerTUI()

    with patch(
        "a2a_handler.tui.server.tab.load_server_catalog",
        return_value=ServerCatalog(global_servers=(default_handler_agent_server(),)),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None
            connect_view = workspace.query_one(ConnectionBar)
            selected = connect_view.get_selected_server()
            select = connect_view.query_one("#server-select", Select)
            labels = [
                prompt
                for prompt, value in select._options
                if value is not Select.BLANK and isinstance(prompt, str)
            ]

            assert selected == default_handler_agent_server()
            assert connect_view.get_url() == DEFAULT_HANDLER_AGENT_URL
            assert labels == ["Handler Agent", "URL..."]


@pytest.mark.asyncio
async def test_connecting_default_handler_agent_auto_starts_local_server() -> None:
    """Connecting the built-in Handler agent starts it before fetching its card."""
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Handler"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Handler"}

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(
                global_servers=(default_handler_agent_server(),)
            ),
        ),
        patch(
            "a2a_handler.tui.server.tab.ensure_default_handler_agent_running",
            AsyncMock(return_value=True),
        ) as mock_ensure_running,
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            await workspace.handle_connect_button()
            await pilot.pause()

            assert workspace.is_connected
            mock_ensure_running.assert_awaited_once_with(DEFAULT_HANDLER_AGENT_URL)
            mock_service.get_card.assert_awaited_once()
            source_badge = workspace.query_one("#badge-source", Static)
            assert "Embedded Server" in str(source_badge.content)
            messages_panel = workspace.query_one(TabbedMessagesPanel)
            assert any(
                "Started Handler's local reference agent" in text
                for text in _chat_texts(messages_panel)
            )


@pytest.mark.asyncio
async def test_auto_starting_default_handler_agent_requires_ollama(monkeypatch) -> None:
    """The TUI should fail early with setup guidance when Ollama is missing."""
    from a2a_handler.tui.server import tab as tab_module

    async def unavailable(_agent_url: str) -> bool:
        return False

    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setattr(tab_module, "_handler_agent_card_available", unavailable)
    monkeypatch.setattr(tab_module.shutil, "which", lambda _name: None)
    popen = Mock()
    monkeypatch.setattr(tab_module.subprocess, "Popen", popen)

    with pytest.raises(RuntimeError, match="requires Ollama"):
        await tab_module.ensure_default_handler_agent_running()

    popen.assert_not_called()


@pytest.mark.asyncio
async def test_auto_starting_default_handler_agent_requires_model(monkeypatch) -> None:
    """The TUI should point users to pull the configured Ollama model."""
    from a2a_handler.tui.server import tab as tab_module

    async def unavailable(_agent_url: str) -> bool:
        return False

    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setattr(tab_module, "_handler_agent_card_available", unavailable)
    monkeypatch.setattr(tab_module.shutil, "which", lambda _name: "/usr/bin/ollama")
    monkeypatch.setattr(tab_module, "check_ollama_model", lambda _model: False)
    popen = Mock()
    monkeypatch.setattr(tab_module.subprocess, "Popen", popen)

    with pytest.raises(RuntimeError, match="ollama pull gemma4:e2b"):
        await tab_module.ensure_default_handler_agent_running()

    popen.assert_not_called()


def test_shutdown_default_handler_agent_waits_after_terminate(monkeypatch) -> None:
    """Auto-started Handler agent cleanup should terminate and reap the child."""
    from a2a_handler.tui.server import tab as tab_module

    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(tab_module, "_handler_agent_process", process)

    tab_module.shutdown_default_handler_agent()

    process.terminate.assert_called_once_with()
    process.wait.assert_called_once_with(
        timeout=tab_module._HANDLER_AGENT_SHUTDOWN_TIMEOUT_SECONDS
    )
    process.kill.assert_not_called()
    assert tab_module._handler_agent_process is None


def test_shutdown_default_handler_agent_kills_after_timeout(monkeypatch) -> None:
    """Cleanup should escalate to kill when the server ignores SIGTERM."""
    from a2a_handler.tui.server import tab as tab_module

    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("handler", 3), None]
    monkeypatch.setattr(tab_module, "_handler_agent_process", process)

    tab_module.shutdown_default_handler_agent()

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 2
    assert tab_module._handler_agent_process is None


@pytest.mark.asyncio
async def test_tui_shutdown_stops_auto_started_handler_agent() -> None:
    """App shutdown should explicitly stop the auto-started Handler agent."""
    from a2a_handler.tui import app as app_module

    app = HandlerTUI()
    with patch.object(app_module, "shutdown_default_handler_agent") as cleanup:
        await app.on_unmount()

    cleanup.assert_called_once_with()


@pytest.mark.asyncio
async def test_connect_starts_fresh_even_when_saved_session_exists(
    patch_server_sources: Mock,
) -> None:
    """Configured server entries should still start fresh when a recent session exists."""
    saved_session = AgentSession(
        agent_url="https://agent.example.com",
        context_id="ctx-saved-123456",
        task_id="task-saved-654321",
        last_used_at="2024-01-02T03:04:05+00:00",
    )
    patch_server_sources.find.return_value = saved_session
    patch_server_sources.list_all.return_value = [saved_session]
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="agent",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}
    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            await workspace.handle_connect_button()
            await pilot.pause()

            assert workspace.state.current_context_id is None
            assert workspace.state.current_task_id is None
            patch_server_sources.set_conversation.assert_called_with(
                "https://agent.example.com",
                None,
                None,
            )
            mock_service.get_task.assert_not_called()


@pytest.mark.asyncio
async def test_connecting_recent_session_hydrates_task_history_but_not_completed_task_id(
    patch_server_sources: Mock,
) -> None:
    """Selecting a recent session should preload history without reusing a completed task."""
    saved_session = AgentSession(
        agent_url="https://agent.example.com",
        context_id="ctx-saved-123456",
        task_id="task-saved-654321",
        last_used_at="2024-01-02T03:04:05+00:00",
    )
    patch_server_sources.find.return_value = saved_session
    patch_server_sources.list_all.return_value = [saved_session]
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="agent",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}
    resumed_task = Task(
        id="task-saved-654321",
        context_id="ctx-saved-123456",
        status=TaskStatus(state=TaskState.completed),
        history=[
            Message(
                message_id="msg-user-1",
                role=Role.user,
                parts=[Part(root=TextPart(text="What can you do?"))],
                context_id="ctx-saved-123456",
                task_id="task-saved-654321",
            ),
            Message(
                message_id="msg-agent-1",
                role=Role.agent,
                parts=[Part(root=TextPart(text="I can help with handler tasks."))],
                context_id="ctx-saved-123456",
                task_id="task-saved-654321",
            ),
        ],
    )

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service.get_task.return_value = resumed_task
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None
            workspace.query_one(
                "#server-select", Select
            ).value = "recent:https://agent.example.com"
            await pilot.pause()

            await workspace.handle_connect_button()
            await pilot.pause()

            live_view = workspace.query_one(ServerView)
            messages_panel = live_view.query_one(TabbedMessagesPanel)
            chat_texts = _chat_texts(messages_panel)

            assert workspace.state.current_context_id == "ctx-saved-123456"
            assert workspace.state.current_task_id is None
            assert sum("What can you do?" in text for text in chat_texts) == 1
            assert any("I can help with handler tasks." in text for text in chat_texts)
            mock_service.get_task.assert_awaited_once_with(
                "task-saved-654321",
                history_length=100,
            )
            assert any("resumed recent session" in text.lower() for text in chat_texts)


@pytest.mark.asyncio
async def test_connecting_recent_session_clears_missing_saved_task_id(
    patch_server_sources: Mock,
) -> None:
    """Recent-session connect should keep the context while dropping a missing task."""
    saved_session = AgentSession(
        agent_url="https://agent.example.com",
        context_id="ctx-saved-123456",
        task_id="task-saved-654321",
        last_used_at="2024-01-02T03:04:05+00:00",
    )
    patch_server_sources.find.return_value = saved_session
    patch_server_sources.list_all.return_value = [saved_session]
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="agent",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service.get_task.side_effect = _missing_task_error("task-saved-654321")
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None
            workspace.query_one(
                "#server-select", Select
            ).value = "recent:https://agent.example.com"
            await pilot.pause()

            await workspace.handle_connect_button()
            await pilot.pause()

            assert workspace.state.current_context_id == "ctx-saved-123456"
            assert workspace.state.current_task_id is None
            assert patch_server_sources.set_conversation.call_args == call(
                "https://agent.example.com",
                "ctx-saved-123456",
                None,
            )

            messages_panel = workspace.query_one(TabbedMessagesPanel)
            texts = _chat_texts(messages_panel)
            assert any(
                "saved task could not be loaded" in text.lower() for text in texts
            )


@pytest.mark.asyncio
async def test_send_retries_without_stale_task_id(
    patch_server_sources: Mock,
) -> None:
    """Sending should retry with context only when a saved task is gone."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="agent",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}
    response_message = Message(
        message_id="msg-1",
        role=Role.agent,
        parts=[Part(root=TextPart(text="Recovered response"))],
        context_id="ctx-saved-123456",
        task_id=None,
    )

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service.send.side_effect = [
            _missing_task_error("task-stale-1"),
            response_message,
        ]
        mock_service.set_credentials = Mock()
        mock_service.clear_credentials = Mock()
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            await workspace.handle_connect_button()
            await pilot.pause()

            workspace.state.current_context_id = "ctx-saved-123456"
            workspace.state.current_task_id = "task-stale-1"
            patch_server_sources.set_conversation.reset_mock()

            workspace.query_one("#message-input", Input).value = "Hello again"
            workspace.handle_send_button()
            await pilot.pause()

            assert mock_service.send.await_args_list == [
                call(
                    "Hello again",
                    context_id="ctx-saved-123456",
                    task_id="task-stale-1",
                ),
                call(
                    "Hello again",
                    context_id="ctx-saved-123456",
                    task_id=None,
                ),
            ]
            assert workspace.state.current_task_id is None
            assert patch_server_sources.set_conversation.call_args == call(
                "https://agent.example.com",
                "ctx-saved-123456",
                None,
            )

            messages_panel = workspace.query_one(TabbedMessagesPanel)
            texts = _chat_texts(messages_panel)
            assert any(
                "retrying with the saved context only" in text.lower() for text in texts
            )
            assert any("Recovered response" in text for text in texts)


@pytest.mark.asyncio
async def test_send_retries_without_completed_task_id(
    patch_server_sources: Mock,
) -> None:
    """Terminal-task errors should fall back to context-only continuation."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="agent",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}
    response_message = Message(
        message_id="msg-1",
        role=Role.agent,
        parts=[Part(root=TextPart(text="Recovered from terminal task"))],
        context_id="ctx-saved-123456",
        task_id=None,
    )

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service.send.side_effect = [
            _completed_task_error("task-completed-1"),
            response_message,
        ]
        mock_service.set_credentials = Mock()
        mock_service.clear_credentials = Mock()
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            await workspace.handle_connect_button()
            await pilot.pause()

            workspace.state.current_context_id = "ctx-saved-123456"
            workspace.state.current_task_id = "task-completed-1"
            patch_server_sources.set_conversation.reset_mock()

            workspace.query_one("#message-input", Input).value = "Hello again"
            workspace.handle_send_button()
            await pilot.pause()

            assert mock_service.send.await_args_list == [
                call(
                    "Hello again",
                    context_id="ctx-saved-123456",
                    task_id="task-completed-1",
                ),
                call(
                    "Hello again",
                    context_id="ctx-saved-123456",
                    task_id=None,
                ),
            ]
            assert workspace.state.current_task_id is None
            assert patch_server_sources.set_conversation.call_args == call(
                "https://agent.example.com",
                "ctx-saved-123456",
                None,
            )

            messages_panel = workspace.query_one(TabbedMessagesPanel)
            texts = _chat_texts(messages_panel)
            assert any(
                "retrying with the saved context only" in text.lower() for text in texts
            )
            assert any("Recovered from terminal task" in text for text in texts)


@pytest.mark.asyncio
async def test_connect_uses_selected_connection_default_auth() -> None:
    """Connect should use the selected connection's default auth when requested."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="staging",
        agent_url="https://staging.example.com",
        auth=ServerAuthConfig(auth_type=AuthType.BEARER, value="profile-token"),
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ) as mock_build_http_client,
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            await workspace.handle_connect_button()
            await pilot.pause()

            credentials = mock_build_http_client.call_args.kwargs["credentials"]
            assert credentials is not None
            assert credentials.auth_type == AuthType.BEARER
            assert credentials.value == "profile-token"

            source_badge = workspace.query_one("#badge-source", Static)
            auth_badge = workspace.query_one("#badge-auth", Static)
            assert "Repository Server" in str(source_badge.content)
            assert "Bearer" in str(auth_badge.content)


@pytest.mark.asyncio
async def test_connect_manual_override_uses_manual_credentials() -> None:
    """Explicit auth override should replace any connection default auth."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="staging",
        agent_url="https://staging.example.com",
        auth=ServerAuthConfig(auth_type=AuthType.BEARER, value="profile-token"),
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ) as mock_build_http_client,
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            server_view = workspace.query_one(ServerView)
            server_view.messages_panel().set_auth_credentials(
                create_bearer_auth("manual-token")
            )
            await workspace.handle_connect_button()
            await pilot.pause()

            credentials = mock_build_http_client.call_args.kwargs["credentials"]
            assert credentials is not None
            assert credentials.auth_type == AuthType.BEARER
            assert credentials.value == "manual-token"

            source_badge = workspace.query_one("#badge-source", Static)
            auth_badge = workspace.query_one("#badge-auth", Static)
            assert "Repository Server" in str(source_badge.content)
            assert "Bearer" in str(auth_badge.content)


@pytest.mark.asyncio
async def test_connect_transitions_server_to_live_view_and_updates_tab_title() -> None:
    """Successful connect should update the unified server view and tab title."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ) as mock_build_http_client,
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            await workspace.handle_connect_button()
            await pilot.pause()

            assert workspace.is_connected
            assert workspace.current_agent_url == "https://agent.example.com"
            assert workspace.query_one(ServerView)

            live_view = workspace.query_one(ServerView)
            messages_panel = live_view.query_one(TabbedMessagesPanel)
            tabs = app.query_one("#server-tabs", Tabs)
            first_tab = tabs.query_one("#server-tab-1", Tab)

            assert first_tab.label_text == "Demo Agent"
            assert messages_panel
            assert len(list(live_view.query("#server-summary"))) == 0

            status_badge = workspace.query_one("#badge-status", Static)
            agent_badge = workspace.query_one("#badge-agent", Static)
            version_badge = workspace.query_one("#badge-version", Static)
            source_badge = workspace.query_one("#badge-source", Static)
            auth_badge = workspace.query_one("#badge-auth", Static)
            assert "Connected" in str(status_badge.content)
            assert status_badge.has_class("badge-success")
            assert "Demo Agent" in str(agent_badge.content)
            assert version_badge.has_class("hidden")
            assert "Repository Server" in str(source_badge.content)
            assert auth_badge.has_class("hidden")

            status_row_ids = [
                child.id for child in workspace.query_one("#server-status-row").children
            ]
            assert status_row_ids == [
                "badge-status",
                "badge-agent",
                "badge-version",
                "badge-source",
                "badge-auth",
                "badge-protocol",
            ]
            mock_build_http_client.assert_called_once_with(credentials=None)
            mock_service_cls.assert_called_once_with(
                new_http_client,
                "https://agent.example.com",
                credentials=None,
            )


@pytest.mark.asyncio
async def test_action_save_connections_warns_when_nothing_is_connected() -> None:
    """Saving without any live connections should surface a warning instead of writing config."""
    app = HandlerTUI()

    with patch("a2a_handler.tui.app.save_connections_to_workspace") as mock_save:
        async with app.run_test() as pilot:
            await pilot.pause()
            notify_mock = Mock()
            app.notify = notify_mock  # type: ignore[method-assign]

            await app.action_save_connections()

            mock_save.assert_not_called()
            notify_mock.assert_called_once_with(
                "No connected servers to add",
                severity="warning",
            )


@pytest.mark.asyncio
async def test_action_save_connections_persists_connected_servers() -> None:
    """Saving connected servers should pass them to the workspace writer and notify success."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
        patch(
            "a2a_handler.tui.app.save_connections_to_workspace",
            return_value=1,
        ) as mock_save,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#connect-btn")
            await pilot.pause()
            notify_mock = Mock()
            app.notify = notify_mock  # type: ignore[method-assign]

            await app.action_save_connections()

            saved_servers = mock_save.call_args.args[0]
            assert len(saved_servers) == 1
            assert saved_servers[0].is_connected is True
            notify_mock.assert_called_once_with(
                "Added 1 server(s) to .handler/servers.toml"
            )


@pytest.mark.asyncio
async def test_action_save_connections_reports_write_failures() -> None:
    """Workspace save errors should be surfaced to the user as error notifications."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
        patch(
            "a2a_handler.tui.app.save_connections_to_workspace",
            side_effect=RuntimeError("disk full"),
        ),
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#connect-btn")
            await pilot.pause()
            notify_mock = Mock()
            app.notify = notify_mock  # type: ignore[method-assign]

            await app.action_save_connections()

            notify_mock.assert_called_once_with(
                "Failed to save: disk full",
                severity="error",
            )


@pytest.mark.asyncio
async def test_action_start_fresh_conversation_resets_context_and_task(
    patch_server_sources: Mock,
) -> None:
    """Starting fresh should keep the connection while replacing context and task."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#connect-btn")
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            workspace.state.current_task_id = "task-existing"
            workspace.query_one(TabbedMessagesPanel).add_system_message(
                "Old conversation"
            )
            patch_server_sources.set_conversation.reset_mock()

            await app.action_start_fresh_conversation()
            await pilot.pause()

            assert workspace.is_connected is True
            assert workspace.state.current_context_id is None
            assert workspace.state.current_task_id is None
            patch_server_sources.set_conversation.assert_called_once_with(
                "https://agent.example.com",
                None,
                None,
            )

            chat_texts = _chat_texts(workspace.query_one(TabbedMessagesPanel))
            assert any(
                "Started a fresh conversation on the current server." in text
                for text in chat_texts
            )
            assert not any("Old conversation" in text for text in chat_texts)


@pytest.mark.asyncio
async def test_action_rename_workspace_server_uses_prompt_and_refreshes_catalog() -> (
    None
):
    """Renaming a workspace server should prompt, write, and refresh picker state."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()

    with patch(
        "a2a_handler.tui.server.tab.load_server_catalog",
        return_value=ServerCatalog(repository_servers=(repo_connection,)),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            def fake_push_screen(screen, callback=None, wait_for_dismiss=False):
                assert callback is not None
                callback("renamed_demo")
                return None

            push_screen_mock = Mock(side_effect=fake_push_screen)
            notify_mock = Mock()
            refresh_catalog_mock = Mock()
            app.push_screen = push_screen_mock  # type: ignore[method-assign]
            app.notify = notify_mock  # type: ignore[method-assign]
            workspace.refresh_server_catalog = refresh_catalog_mock  # type: ignore[method-assign]

            with patch("a2a_handler.tui.app.rename_workspace_server") as mock_rename:
                app.action_rename_workspace_server()

            mock_rename.assert_called_once_with("demo", "renamed_demo")
            refresh_catalog_mock.assert_called_once_with()
            notify_mock.assert_called_once_with(
                "Renamed saved workspace server to renamed_demo"
            )


@pytest.mark.asyncio
async def test_action_remove_workspace_server_confirms_before_refreshing_catalog() -> (
    None
):
    """Removing a workspace server should require confirmation before deleting."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()

    with patch(
        "a2a_handler.tui.server.tab.load_server_catalog",
        return_value=ServerCatalog(repository_servers=(repo_connection,)),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            def fake_push_screen(screen, callback=None, wait_for_dismiss=False):
                assert callback is not None
                callback(True)
                return None

            push_screen_mock = Mock(side_effect=fake_push_screen)
            notify_mock = Mock()
            refresh_catalog_mock = Mock()
            app.push_screen = push_screen_mock  # type: ignore[method-assign]
            app.notify = notify_mock  # type: ignore[method-assign]
            workspace.refresh_server_catalog = refresh_catalog_mock  # type: ignore[method-assign]

            with patch("a2a_handler.tui.app.remove_workspace_server") as mock_remove:
                app.action_remove_workspace_server()

            mock_remove.assert_called_once_with("demo")
            refresh_catalog_mock.assert_called_once_with()
            notify_mock.assert_called_once_with(
                "Removed saved workspace server 'demo'. Live tab stays open."
            )


@pytest.mark.asyncio
async def test_action_forget_saved_session_confirms_before_refreshing_catalog(
    patch_server_sources: Mock,
) -> None:
    """Forgetting a saved session should confirm, clear storage, and refresh recents."""
    saved_session = AgentSession(
        agent_url="https://agent.example.com",
        context_id="ctx-saved-123456",
        task_id="task-saved-654321",
        last_used_at="2024-01-02T03:04:05+00:00",
    )
    patch_server_sources.find.side_effect = (
        lambda agent_url: saved_session
        if agent_url == "https://agent.example.com"
        else None
    )
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()

    with patch(
        "a2a_handler.tui.server.tab.load_server_catalog",
        return_value=ServerCatalog(repository_servers=(repo_connection,)),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            def fake_push_screen(screen, callback=None, wait_for_dismiss=False):
                assert callback is not None
                callback(True)
                return None

            push_screen_mock = Mock(side_effect=fake_push_screen)
            notify_mock = Mock()
            refresh_catalog_mock = Mock()
            app.push_screen = push_screen_mock  # type: ignore[method-assign]
            app.notify = notify_mock  # type: ignore[method-assign]
            workspace.refresh_server_catalog = refresh_catalog_mock  # type: ignore[method-assign]

            app.action_forget_saved_session()

            patch_server_sources.clear.assert_called_once_with(
                "https://agent.example.com"
            )
            refresh_catalog_mock.assert_called_once_with()
            notify_mock.assert_called_once_with(
                "Forgot saved session for 'demo'. Live tab stays open."
            )


@pytest.mark.asyncio
async def test_connect_validates_agent_url_before_service_call() -> None:
    """Malformed URLs should be rejected from the connect view."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace = app.query_one(ServerTabs).get_active_server()
        assert workspace is not None

        connect_view = workspace.query_one(ConnectionBar)
        from a2a_handler.tui.server.types import MANUAL_SERVER_ID

        server_select = connect_view.query_one("#server-select", Select)
        server_select.value = MANUAL_SERVER_ID
        connect_view._sync_manual_input()
        connect_view.query_one("#manual-agent-url").value = "not-a-url"
        await workspace.handle_connect_button()
        await pilot.pause()

        messages_panel = workspace.query_one(TabbedMessagesPanel)
        texts = _chat_texts(messages_panel)
        assert any("valid http(s) URL" in t for t in texts)


@pytest.mark.asyncio
async def test_pressing_enter_in_manual_url_connects_active_server() -> None:
    """Submitting the manual URL field should trigger the same connect flow."""
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Manual Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Manual Agent"}

    with (
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            manual_input = workspace.query_one("#manual-agent-url", Input)
            manual_input.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert workspace.is_connected
            assert workspace.current_agent_url == "http://localhost:8000"
            mock_service.get_card.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_button_submits_typed_message_through_ui() -> None:
    """Typing into the compose input and clicking send should drive the worker flow."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}
    response_message = Message(
        message_id="msg-1",
        role=Role.agent,
        parts=[Part(root=TextPart(text="Hello from the agent"))],
        context_id="ctx-response",
        task_id="task-response",
    )

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service.send.return_value = response_message
        mock_service.set_credentials = Mock()
        mock_service.clear_credentials = Mock()
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            await pilot.click("#connect-btn")
            await pilot.pause()

            initial_context_id = workspace.state.current_context_id
            assert initial_context_id is None

            await pilot.click("#message-input")
            await pilot.press(
                "H",
                "e",
                "l",
                "l",
                "o",
                "space",
                "a",
                "g",
                "e",
                "n",
                "t",
            )
            await pilot.click("#send-btn")
            await pilot.pause()

            mock_service.send.assert_awaited_once_with(
                "Hello agent",
                context_id=initial_context_id,
                task_id=None,
            )
            assert workspace.query_one("#message-input", Input).value == ""
            assert workspace.state.current_context_id == "ctx-response"
            assert workspace.state.current_task_id == "task-response"

            chat_texts = _chat_texts(workspace.query_one(TabbedMessagesPanel))
            assert any("Hello agent" in text for text in chat_texts)
            assert any("Hello from the agent" in text for text in chat_texts)


@pytest.mark.asyncio
async def test_send_shows_loading_indicator_while_waiting_for_response() -> None:
    """Slow A2A responses should show an in-flight loading indicator."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}
    response_message = Message(
        message_id="msg-1",
        role=Role.agent,
        parts=[Part(root=TextPart(text="Delayed response"))],
        context_id="ctx-response",
        task_id=None,
    )
    send_started = asyncio.Event()
    release_response = asyncio.Event()

    async def slow_send(*args, **kwargs):
        send_started.set()
        await release_response.wait()
        return response_message

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service.send.side_effect = slow_send
        mock_service.set_credentials = Mock()
        mock_service.clear_credentials = Mock()
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None
            await workspace.handle_connect_button()
            await pilot.pause()

            message_input = workspace.query_one("#message-input", Input)
            message_input.value = "Slow request"
            workspace.handle_send_button()
            await pilot.pause()
            await asyncio.wait_for(send_started.wait(), timeout=1)
            await pilot.pause()

            loading_label = workspace.query_one("#send-loading-label", Static)
            assert "Waiting for agent" in str(loading_label.content)
            assert not loading_label.has_class("hidden")
            assert message_input.disabled is True
            assert workspace.query_one("#send-btn").disabled is True

            release_response.set()
            await pilot.pause()
            await pilot.pause()

            assert loading_label.has_class("hidden")
            assert message_input.disabled is False
            chat_texts = _chat_texts(workspace.query_one(TabbedMessagesPanel))
            assert any("Delayed response" in text for text in chat_texts)


@pytest.mark.asyncio
async def test_terminal_task_response_is_not_reused_for_follow_up_messages(
    patch_server_sources: Mock,
) -> None:
    """Completed task responses should keep the context but drop the task ID."""
    repo_connection = _make_server(
        source=ServerSource.REPOSITORY,
        name="demo",
        agent_url="https://agent.example.com",
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.protocol_version = None
    mock_card.version = None
    mock_card.model_dump.return_value = {"name": "Demo Agent"}
    first_response = Task(
        id="task-response-1",
        context_id="ctx-response",
        status=TaskStatus(state=TaskState.completed),
        history=[
            Message(
                message_id="msg-agent-1",
                role=Role.agent,
                parts=[Part(root=TextPart(text="First completed reply"))],
                context_id="ctx-response",
                task_id="task-response-1",
            )
        ],
    )
    second_response = Task(
        id="task-response-2",
        context_id="ctx-response",
        status=TaskStatus(state=TaskState.completed),
        history=[
            Message(
                message_id="msg-agent-2",
                role=Role.agent,
                parts=[Part(root=TextPart(text="Second completed reply"))],
                context_id="ctx-response",
                task_id="task-response-2",
            )
        ],
    )

    with (
        patch(
            "a2a_handler.tui.server.tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server.tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server.tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service.send.side_effect = [first_response, second_response]
        mock_service.set_credentials = Mock()
        mock_service.clear_credentials = Mock()
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            await workspace.handle_connect_button()
            await pilot.pause()

            initial_context_id = workspace.state.current_context_id
            assert initial_context_id is None

            workspace.query_one("#message-input", Input).value = "Hello once"
            workspace.handle_send_button()
            await pilot.pause()

            assert workspace.state.current_context_id == "ctx-response"
            assert workspace.state.current_task_id is None
            assert patch_server_sources.set_conversation.call_args == call(
                "https://agent.example.com",
                "ctx-response",
                None,
            )

            workspace.query_one("#message-input", Input).value = "Hello twice"
            workspace.handle_send_button()
            await pilot.pause()

            assert mock_service.send.await_args_list == [
                call(
                    "Hello once",
                    context_id=initial_context_id,
                    task_id=None,
                ),
                call(
                    "Hello twice",
                    context_id="ctx-response",
                    task_id=None,
                ),
            ]

            texts = _chat_texts(workspace.query_one(TabbedMessagesPanel))
            assert not any(
                "retrying with the saved context only" in text.lower() for text in texts
            )


@pytest.mark.asyncio
async def test_close_server_action_removes_active_server_tab() -> None:
    """Closing the active server should remove the tab and switch back."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()

        tabs = app.query_one("#server-tabs", Tabs)
        assert tabs.tab_count == 2
        assert tabs.active == "server-tab-2"

        await app.action_close_server()
        await pilot.pause()

        assert tabs.tab_count == 1
        assert tabs.active == "server-tab-1"

        active_server = app.query_one(ServerTabs).get_active_server()
        assert active_server is not None
        assert active_server.server_id == "server-1"
