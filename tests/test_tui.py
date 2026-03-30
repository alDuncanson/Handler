"""Tests for the server-based TUI shell."""

from collections.abc import Generator
import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest
from a2a.types import Message, Part, Role, Task, TaskState, TaskStatus, TextPart
from textual.widgets import RadioButton, Select, Static, Tab, Tabs

from a2a_handler.auth import AuthType, create_bearer_auth
from a2a_handler.servers import (
    ServerAuthConfig,
    ServerCatalog,
    ServerDefinition,
    ServerSource,
)
from a2a_handler.session import AgentSession
from a2a_handler.service import TaskResult
from a2a_handler.tui import HandlerTUI
from a2a_handler.tui.app import HandlerTUI as HandlerTUIApplication
from a2a_handler.tui.components import TabbedMessagesPanel
from a2a_handler.tui.server_tab import ServerTab
from a2a_handler.tui.server_tabs import ServerTabs
from a2a_handler.tui.server_views import ServerConnectView, ServerLiveView


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


@pytest.fixture(autouse=True)
def patch_server_sources() -> Generator[Mock, None, None]:
    """Keep TUI tests isolated from user server and session files."""
    session_store = Mock()
    session_store.find.return_value = None
    session_store.list_all.return_value = []
    session_store.recent_agent_urls.return_value = []

    with (
        patch(
            "a2a_handler.tui.server_tab.load_server_catalog",
            return_value=ServerCatalog(),
        ),
        patch(
            "a2a_handler.tui.server_tab.get_session_store",
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
        connect_view = workspace.query_one(ServerConnectView)
        live_view = workspace.query_one(ServerLiveView)

        assert connect_view
        assert live_view
        assert workspace.region.height > 5
        assert connect_view.query_one("#server-bar")
        assert len(list(live_view.query("#server-summary"))) == 0

        status = connect_view.query_one("#server-status-row", Static)
        assert str(status.content) == "Disconnected"
        assert status.has_class("status-info")


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
async def test_initial_bearer_token_seeds_first_server_connect_view() -> None:
    """The first server should inherit an explicit auth override."""
    app = HandlerTUI(initial_bearer_token="test-token")

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace = app.query_one(ServerTabs).get_active_server()
        assert workspace is not None

        connect_view = workspace.query_one(ServerConnectView)
        credentials = connect_view.get_auth_credentials()

        assert workspace.state.auth_overridden
        assert credentials is not None
        assert credentials.auth_type == AuthType.BEARER
        assert credentials.value == "test-token"


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
        "a2a_handler.tui.server_tab.load_server_catalog",
        return_value=ServerCatalog(repository_servers=(repo_connection,)),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            connect_view = workspace.query_one(ServerConnectView)

            assert connect_view.get_selected_server() == repo_connection
            assert connect_view.get_url() == "https://staging.example.com"


@pytest.mark.asyncio
async def test_recent_connections_are_loaded_from_session_recency(
    patch_server_sources: Mock,
) -> None:
    """Recent servers should appear in the single server selector."""
    patch_server_sources.recent_agent_urls.return_value = [
        "https://recent.example.com"
    ]
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace = app.query_one(ServerTabs).get_active_server()
        assert workspace is not None

        connect_view = workspace.query_one(ServerConnectView)
        server_select = connect_view.query_one("#server-select", Select)
        server_select.value = "recent:https://recent.example.com"

        selected = connect_view.get_selected_server()
        assert selected is not None
        assert selected.source == ServerSource.RECENT
        assert selected.agent_url == "https://recent.example.com"


@pytest.mark.asyncio
async def test_auto_resume_when_saved_session_exists(
    patch_server_sources: Mock,
) -> None:
    """Auto-resume should use saved context when a session exists."""
    patch_server_sources.find.return_value = AgentSession(
        agent_url="https://agent.example.com",
        context_id="ctx-saved-123456",
        task_id="task-saved-654321",
    )
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
            "a2a_handler.tui.server_tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server_tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server_tab.A2AService") as mock_service_cls,
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

            assert workspace.current_context_id == "ctx-saved-123456"
            assert workspace.state.resumed
            patch_server_sources.set_conversation.assert_called_with(
                "https://agent.example.com",
                "ctx-saved-123456",
                "task-saved-654321",
            )


@pytest.mark.asyncio
async def test_auto_resume_hydrates_saved_task_history(
    patch_server_sources: Mock,
) -> None:
    """Auto-resume should preload prior task history into the live workspace."""
    patch_server_sources.find.return_value = AgentSession(
        agent_url="https://agent.example.com",
        context_id="ctx-saved-123456",
        task_id="task-saved-654321",
    )
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
            "a2a_handler.tui.server_tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server_tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server_tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service.get_task.return_value = TaskResult(task=resumed_task)
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            await workspace.handle_connect_button()
            await pilot.pause()

            live_view = workspace.query_one(ServerLiveView)
            messages_panel = live_view.query_one(TabbedMessagesPanel)
            chat_texts = _chat_texts(messages_panel)

            assert sum("What can you do?" in text for text in chat_texts) == 1
            assert any("I can help with handler tasks." in text for text in chat_texts)
            mock_service.get_task.assert_awaited_once_with(
                "task-saved-654321",
                history_length=100,
            )


@pytest.mark.asyncio
async def test_force_fresh_ignores_saved_context(
    patch_server_sources: Mock,
) -> None:
    """Force fresh via command palette should ignore saved context."""
    patch_server_sources.find.return_value = AgentSession(
        agent_url="https://agent.example.com",
        context_id="ctx-saved-123456",
        task_id="task-saved-654321",
    )
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
            "a2a_handler.tui.server_tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server_tab.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.server_tab.A2AService") as mock_service_cls,
        patch("a2a_handler.tui.server_tab.uuid.uuid4", return_value=fresh_context),
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            await workspace.handle_connect_button(force_fresh=True)
            await pilot.pause()

            assert workspace.current_context_id == str(fresh_context)
            assert not workspace.state.resumed
            patch_server_sources.set_conversation.assert_called_with(
                "https://agent.example.com",
                str(fresh_context),
                None,
            )


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
            "a2a_handler.tui.server_tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server_tab.build_http_client",
            return_value=new_http_client,
        ) as mock_build_http_client,
        patch("a2a_handler.tui.server_tab.A2AService") as mock_service_cls,
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
            assert (
                workspace.state.auth_source == "repository server 'staging' default"
            )


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
            "a2a_handler.tui.server_tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server_tab.build_http_client",
            return_value=new_http_client,
        ) as mock_build_http_client,
        patch("a2a_handler.tui.server_tab.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(ServerTabs).get_active_server()
            assert workspace is not None

            connect_view = workspace.query_one(ServerConnectView)
            connect_view.set_auth_credentials(create_bearer_auth("manual-token"))
            workspace.state.auth_overridden = True
            await workspace.handle_connect_button()
            await pilot.pause()

            credentials = mock_build_http_client.call_args.kwargs["credentials"]
            assert credentials is not None
            assert credentials.auth_type == AuthType.BEARER
            assert credentials.value == "manual-token"
            assert workspace.state.auth_source == "manual override"


@pytest.mark.asyncio
async def test_connect_transitions_server_to_live_view_and_updates_tab_title() -> (
    None
):
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
            "a2a_handler.tui.server_tab.load_server_catalog",
            return_value=ServerCatalog(repository_servers=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.server_tab.build_http_client",
            return_value=new_http_client,
        ) as mock_build_http_client,
        patch("a2a_handler.tui.server_tab.A2AService") as mock_service_cls,
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
            assert workspace.query_one(ServerLiveView)

            live_view = workspace.query_one(ServerLiveView)
            messages_panel = live_view.query_one(TabbedMessagesPanel)
            status = workspace.query_one("#server-status-row", Static)
            tabs = app.query_one("#server-tabs", Tabs)
            first_tab = tabs.query_one("#server-tab-1", Tab)

            assert first_tab.label_text == "Demo Agent"
            assert messages_panel
            assert len(list(live_view.query("#server-summary"))) == 0
            assert "Connected" in str(status.content)
            assert "Demo Agent" in str(status.content)
            assert status.has_class("status-success")
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

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace = app.query_one(ServerTabs).get_active_server()
        assert workspace is not None

        connect_view = workspace.query_one(ServerConnectView)
        from a2a_handler.tui.server_types import MANUAL_SERVER_ID

        server_select = connect_view.query_one("#server-select", Select)
        server_select.value = MANUAL_SERVER_ID
        connect_view._sync_manual_input()
        connect_view.query_one("#manual-agent-url").value = "not-a-url"
        await workspace.handle_connect_button()
        await pilot.pause()

        status = connect_view.query_one("#server-status-row", Static)

        assert "valid http(s) URL" in str(status.content)


def test_resolve_server_credentials_uses_server_default_auth() -> None:
    server = ServerTab(server_id="server-test", title="Server Test")
    server_def = _make_server(
        source=ServerSource.REPOSITORY,
        name="staging",
        agent_url="https://staging.example.com",
        auth=ServerAuthConfig(auth_type=AuthType.BEARER, value="profile-token"),
    )
    server._server_credentials = {
        server_def.server_id: create_bearer_auth("profile-token")
    }

    credentials, source, warning = server._resolve_auth(
        selected_server=server_def,
        override_credentials=None,
    )

    assert credentials is not None
    assert credentials.value == "profile-token"
    assert source == "repository server 'staging' default"
    assert warning is None


def test_resolve_server_credentials_uses_manual_override() -> None:
    server = ServerTab(server_id="server-test", title="Server Test")
    manual = create_bearer_auth("manual-token")

    credentials, source, warning = server._resolve_auth(
        selected_server=None,
        override_credentials=manual,
    )

    assert credentials == manual
    assert source == "manual override"
    assert warning is None
