"""Tests for the server-based TUI shell."""

from collections.abc import Generator
import uuid
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
from textual.widgets import Input, Select, Static, Tab, Tabs

from a2a_handler.auth import AuthType, create_bearer_auth
from a2a_handler.servers import (
    ServerAuthConfig,
    ServerCatalog,
    ServerDefinition,
    ServerSource,
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
async def test_footer_shows_quit_and_server_hotkeys() -> None:
    """Global bindings should be visible and ctrl+c should override copy."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.screen.active_bindings["ctrl+c"].binding.action == "quit"

        footer = app.query_one("Footer")
        footer_labels = [str(child.render()) for child in footer.children]

        assert any("Ctrl+C" in label and "Quit" in label for label in footer_labels)
        assert any("Ctrl+B" in label for label in footer_labels)
        assert any("Ctrl+T" in label for label in footer_labels)
        assert any(
            "Ctrl+N" in label and "New Server" in label for label in footer_labels
        )


@pytest.mark.asyncio
async def test_command_palette_is_centered_instead_of_full_width() -> None:
    """The command palette should render as a centered dialog, not a full-width sheet."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+p")
        await pilot.pause(1)

        palette = app.screen_stack[-1]
        command_list = palette.query_one("CommandList")

        assert command_list.region.width < app.screen.region.width
        assert command_list.region.x > 0


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
        assert "Save Connections to Workspace" not in titles


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
            assert "Close Server 2" in titles
            assert "Save Connections to Workspace" in titles

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

        app.screen.maximize = Mock()  # type: ignore[method-assign]
        app.screen.minimize = Mock()  # type: ignore[method-assign]

        app.action_toggle_maximize()

        app.screen.maximize.assert_called_once_with(messages_panel)
        assert app._is_maximized is True

        app.action_toggle_maximize()

        app.screen.minimize.assert_called_once_with()
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
    """Auto-connected OAuth2 servers should sync resolved credentials into Auth."""
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

    app = HandlerTUI()
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
    mock_card.model_dump.return_value = {"name": "Demo Agent"}
    fresh_context = uuid.UUID("12345678-1234-5678-1234-567812345678")

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
        patch("a2a_handler.tui.server.tab.uuid.uuid4", return_value=fresh_context),
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

            assert workspace.state.current_context_id == str(fresh_context)
            assert workspace.state.current_task_id is None
            patch_server_sources.set_conversation.assert_called_with(
                "https://agent.example.com",
                str(fresh_context),
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
            workspace.query_one("#server-select", Select).value = (
                "recent:https://agent.example.com"
            )
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
            assert any(
                "resumed recent session" in text.lower() for text in chat_texts
            )


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
            workspace.query_one("#server-select", Select).value = (
                "recent:https://agent.example.com"
            )
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
            assert workspace.state.auth_source == "repository server 'staging' default"


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
            assert "Connected" in str(status_badge.content)
            assert status_badge.has_class("badge-success")
            assert "Demo Agent" in str(agent_badge.content)
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
            app.notify = Mock()  # type: ignore[method-assign]

            await app.action_save_connections()

            mock_save.assert_not_called()
            app.notify.assert_called_once_with(
                "No connected servers to save",
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
            app.notify = Mock()  # type: ignore[method-assign]

            await app.action_save_connections()

            saved_servers = mock_save.call_args.args[0]
            assert len(saved_servers) == 1
            assert saved_servers[0].is_connected is True
            app.notify.assert_called_once_with(
                "Saved 1 server(s) to .handler/servers.toml"
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
            app.notify = Mock()  # type: ignore[method-assign]

            await app.action_save_connections()

            app.notify.assert_called_once_with(
                "Failed to save: disk full",
                severity="error",
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
            assert initial_context_id is not None

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
