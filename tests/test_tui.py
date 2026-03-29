"""Tests for the workspace-based TUI shell."""

from collections.abc import Generator
import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest
from a2a.types import Message, Part, Role, Task, TaskState, TaskStatus, TextPart
from textual.widgets import RadioButton, Select, Static, Tab, Tabs

from a2a_handler.auth import AuthType, create_bearer_auth
from a2a_handler.connections import (
    ConnectionAuthConfig,
    ConnectionCatalog,
    ConnectionDefinition,
    ConnectionSource,
)
from a2a_handler.session import AgentSession
from a2a_handler.service import TaskResult
from a2a_handler.tui import HandlerTUI
from a2a_handler.tui.app import HandlerTUI as HandlerTUIApplication
from a2a_handler.tui.components import TabbedMessagesPanel
from a2a_handler.tui.workspace import (
    RemoteConnectView,
    RemoteLiveView,
    RemoteWorkspace,
    WorkspaceAuthMode,
    WorkspaceLaunchMode,
    WorkspaceTabs,
)


def _chat_texts(messages_panel: TabbedMessagesPanel) -> list[str]:
    chat = messages_panel.query_one("#chat")
    return [str(getattr(widget, "content", "")) for widget in chat.children]


def _make_connection(
    *,
    source: ConnectionSource,
    name: str,
    agent_url: str,
    auth: ConnectionAuthConfig | None = None,
) -> ConnectionDefinition:
    return ConnectionDefinition(
        connection_id=f"{source.value}:{name}",
        source=source,
        name=name,
        agent_url=agent_url,
        auth=auth,
        origin_label=source.value.capitalize(),
    )


@pytest.fixture(autouse=True)
def patch_workspace_sources() -> Generator[Mock, None, None]:
    """Keep TUI tests isolated from user connection and session files."""
    session_store = Mock()
    session_store.list_all.return_value = []
    session_store.recent_agent_urls.return_value = []

    with (
        patch(
            "a2a_handler.tui.workspace.load_connection_catalog",
            return_value=ConnectionCatalog(),
        ),
        patch(
            "a2a_handler.tui.workspace.get_session_store",
            return_value=session_store,
        ),
    ):
        yield session_store


@pytest.mark.asyncio
async def test_app_starts_with_workspace_shell_and_initial_remote() -> None:
    """Startup should create one unified workspace with the connection bar ready."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace_tabs = app.query_one(WorkspaceTabs)
        workspace = workspace_tabs.get_active_workspace()

        assert workspace is not None
        assert not workspace.is_connected
        connect_view = workspace.query_one(RemoteConnectView)
        live_view = workspace.query_one(RemoteLiveView)

        assert connect_view
        assert live_view
        assert workspace.region.height > 5
        assert connect_view.query_one("#connection-bar")
        assert len(list(live_view.query("#workspace-summary"))) == 0

        connect_status = connect_view.query_one("#connect-status", Static)
        assert str(connect_status.content) == "Disconnected"
        assert connect_status.has_class("status-info")


def test_workspace_shell_does_not_hijack_tab_navigation() -> None:
    """Workspace switching should not steal the Tab key from form controls."""
    assert all(binding.key != "tab" for binding in WorkspaceTabs.BINDINGS)
    assert all(binding.key != "shift+tab" for binding in WorkspaceTabs.BINDINGS)


def test_app_uses_ctrl_c_for_quit_binding() -> None:
    """The app should advertise ctrl+c as the quit shortcut."""
    assert any(binding.key == "ctrl+c" for binding in HandlerTUIApplication.BINDINGS)
    assert all(binding.key != "ctrl+q" for binding in HandlerTUIApplication.BINDINGS)


def test_app_advertises_workspace_hotkeys() -> None:
    """Workspace shortcuts should be available at the app level."""
    bindings_by_key = {
        binding.key: binding.action for binding in HandlerTUIApplication.BINDINGS
    }

    assert bindings_by_key["ctrl+n"] == "new_workspace"
    assert bindings_by_key["ctrl+b"] == "previous_workspace"
    assert bindings_by_key["ctrl+t"] == "next_workspace"


@pytest.mark.asyncio
async def test_footer_shows_quit_and_workspace_hotkeys() -> None:
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
            "Ctrl+N" in label and "New Remote" in label for label in footer_labels
        )


@pytest.mark.asyncio
async def test_command_palette_is_centered_instead_of_full_width() -> None:
    """The command palette should render as a centered dialog, not a full-width sheet."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/")
        await pilot.pause(1)

        palette = app.screen_stack[-1]
        command_list = palette.query_one("CommandList")

        assert command_list.region.width < app.screen.region.width
        assert command_list.region.x > 0


@pytest.mark.asyncio
async def test_initial_bearer_token_seeds_first_workspace_connect_view() -> None:
    """The first workspace should inherit an explicit auth override."""
    app = HandlerTUI(initial_bearer_token="test-token")

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace = app.query_one(WorkspaceTabs).get_active_workspace()
        assert workspace is not None

        connect_view = workspace.query_one(RemoteConnectView)
        credentials = connect_view.get_auth_credentials()

        assert connect_view.get_auth_mode() == WorkspaceAuthMode.OVERRIDE
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
async def test_workspace_hotkeys_create_and_switch_remotes() -> None:
    """Global shortcuts should add and cycle remote workspace tabs."""
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()

        workspace_tabs = app.query_one(WorkspaceTabs)
        tabs = app.query_one("#workspace-tabs", Tabs)
        active_workspace = workspace_tabs.get_active_workspace()

        assert len(workspace_tabs.iter_workspaces()) == 2
        assert tabs.active == "workspace-tab-2"
        assert active_workspace is not None

        active_workspace.query_one("#launch-mode-select", Select).focus()
        await pilot.press("ctrl+b")
        await pilot.pause()

        assert tabs.active == "workspace-tab-1"

        active_workspace = workspace_tabs.get_active_workspace()
        assert active_workspace is not None

        active_workspace.query_one("#launch-mode-select", Select).focus()
        await pilot.press("ctrl+t")
        await pilot.pause()

        assert tabs.active == "workspace-tab-2"


@pytest.mark.asyncio
async def test_repository_connection_tab_is_default_and_selects_first_connection() -> (
    None
):
    """Repository connections should be the primary default tab and selection."""
    app = HandlerTUI()
    repo_connection = _make_connection(
        source=ConnectionSource.REPOSITORY,
        name="staging",
        agent_url="https://staging.example.com",
    )

    with patch(
        "a2a_handler.tui.workspace.load_connection_catalog",
        return_value=ConnectionCatalog(repository_connections=(repo_connection,)),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(WorkspaceTabs).get_active_workspace()
            assert workspace is not None

            connect_view = workspace.query_one(RemoteConnectView)

            assert connect_view.get_active_source() == ConnectionSource.REPOSITORY
            assert connect_view.get_selected_connection() == repo_connection
            assert connect_view.get_url() == "https://staging.example.com"


@pytest.mark.asyncio
async def test_recent_connections_are_loaded_from_session_recency(
    patch_workspace_sources: Mock,
) -> None:
    """Recent tab should reflect session MRU URLs distinctly from configured connections."""
    patch_workspace_sources.recent_agent_urls.return_value = [
        "https://recent.example.com"
    ]
    app = HandlerTUI()

    async with app.run_test() as pilot:
        await pilot.pause()

        workspace = app.query_one(WorkspaceTabs).get_active_workspace()
        assert workspace is not None

        connect_view = workspace.query_one(RemoteConnectView)
        connect_view.activate_source(ConnectionSource.RECENT)
        workspace._refresh_connect_selection()

        selected = connect_view.get_selected_connection()
        assert selected is not None
        assert selected.source == ConnectionSource.RECENT
        assert selected.agent_url == "https://recent.example.com"


@pytest.mark.asyncio
async def test_saved_session_defaults_matching_repository_connection_to_resume_mode(
    patch_workspace_sources: Mock,
) -> None:
    """Matching saved contexts should make resume the default launch mode."""
    patch_workspace_sources.list_all.return_value = [
        AgentSession(
            agent_url="https://saved.example.com",
            context_id="ctx-saved-123456",
            task_id="task-saved-654321",
        )
    ]
    repo_connection = _make_connection(
        source=ConnectionSource.REPOSITORY,
        name="saved",
        agent_url="https://saved.example.com",
    )
    app = HandlerTUI()

    with patch(
        "a2a_handler.tui.workspace.load_connection_catalog",
        return_value=ConnectionCatalog(repository_connections=(repo_connection,)),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(WorkspaceTabs).get_active_workspace()
            assert workspace is not None

            connect_view = workspace.query_one(RemoteConnectView)
            conversation_status = connect_view.query_one("#conversation-status", Static)

            assert "Resume available" in str(conversation_status.content)
            assert connect_view.get_launch_mode() == WorkspaceLaunchMode.RESUME_SESSION


@pytest.mark.asyncio
async def test_connect_view_selectors_and_auth_panel_remain_exclusive(
    patch_workspace_sources: Mock,
) -> None:
    """Top-bar selectors and auth radios should settle on one active choice."""
    patch_workspace_sources.list_all.return_value = [
        AgentSession(
            agent_url="https://saved.example.com",
            context_id="ctx-saved-123456",
            task_id="task-saved-654321",
        )
    ]
    repo_connection = _make_connection(
        source=ConnectionSource.REPOSITORY,
        name="saved",
        agent_url="https://saved.example.com",
    )
    app = HandlerTUI()

    with patch(
        "a2a_handler.tui.workspace.load_connection_catalog",
        return_value=ConnectionCatalog(repository_connections=(repo_connection,)),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(WorkspaceTabs).get_active_workspace()
            assert workspace is not None

            connect_view = workspace.query_one(RemoteConnectView)
            launch_select = connect_view.query_one("#launch-mode-select", Select)
            auth_mode_select = connect_view.query_one("#auth-mode-select", Select)

            launch_select.value = WorkspaceLaunchMode.START_FRESH.value
            await pilot.pause()
            launch_select.value = WorkspaceLaunchMode.RESUME_SESSION.value
            await pilot.pause()

            assert connect_view.get_launch_mode() == WorkspaceLaunchMode.RESUME_SESSION

            auth_mode_select.value = WorkspaceAuthMode.OVERRIDE.value
            await pilot.pause()
            auth_mode_select.value = WorkspaceAuthMode.USE_CONNECTION_DEFAULT.value
            await pilot.pause()

            assert (
                connect_view.get_auth_mode() == WorkspaceAuthMode.USE_CONNECTION_DEFAULT
            )

            auth_mode_select.value = WorkspaceAuthMode.OVERRIDE.value
            await pilot.pause()
            workspace.query_one("#auth-bearer", RadioButton).toggle()
            await pilot.pause()
            workspace.query_one("#auth-api-key", RadioButton).toggle()
            await pilot.pause()

            assert workspace.query_one("#auth-api-key", RadioButton).value
            assert not workspace.query_one("#auth-bearer", RadioButton).value


@pytest.mark.asyncio
async def test_connect_resume_mode_reuses_saved_context(
    patch_workspace_sources: Mock,
) -> None:
    """Resume mode should carry the saved context into the live workspace."""
    patch_workspace_sources.list_all.return_value = [
        AgentSession(
            agent_url="https://agent.example.com",
            context_id="ctx-saved-123456",
            task_id="task-saved-654321",
        )
    ]
    repo_connection = _make_connection(
        source=ConnectionSource.REPOSITORY,
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
            "a2a_handler.tui.workspace.load_connection_catalog",
            return_value=ConnectionCatalog(repository_connections=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.workspace.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.workspace.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(WorkspaceTabs).get_active_workspace()
            assert workspace is not None

            await workspace.handle_connect_button()
            await pilot.pause()

            assert workspace.current_context_id == "ctx-saved-123456"
            patch_workspace_sources.set_conversation.assert_called_with(
                "https://agent.example.com",
                "ctx-saved-123456",
                "task-saved-654321",
            )


@pytest.mark.asyncio
async def test_connect_resume_mode_hydrates_saved_task_history(
    patch_workspace_sources: Mock,
) -> None:
    """Resume mode should preload prior task history into the live workspace."""
    patch_workspace_sources.list_all.return_value = [
        AgentSession(
            agent_url="https://agent.example.com",
            context_id="ctx-saved-123456",
            task_id="task-saved-654321",
        )
    ]
    repo_connection = _make_connection(
        source=ConnectionSource.REPOSITORY,
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
            "a2a_handler.tui.workspace.load_connection_catalog",
            return_value=ConnectionCatalog(repository_connections=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.workspace.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.workspace.A2AService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service.get_task.return_value = TaskResult(task=resumed_task)
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(WorkspaceTabs).get_active_workspace()
            assert workspace is not None

            await workspace.handle_connect_button()
            await pilot.pause()

            live_view = workspace.query_one(RemoteLiveView)
            messages_panel = live_view.query_one(TabbedMessagesPanel)
            chat_texts = _chat_texts(messages_panel)

            assert sum("What can you do?" in text for text in chat_texts) == 1
            assert any("I can help with handler tasks." in text for text in chat_texts)
            mock_service.get_task.assert_awaited_once_with(
                "task-saved-654321",
                history_length=100,
            )


@pytest.mark.asyncio
async def test_connect_start_fresh_ignores_saved_context(
    patch_workspace_sources: Mock,
) -> None:
    """Users can explicitly start fresh even when a saved context exists."""
    patch_workspace_sources.list_all.return_value = [
        AgentSession(
            agent_url="https://agent.example.com",
            context_id="ctx-saved-123456",
            task_id="task-saved-654321",
        )
    ]
    repo_connection = _make_connection(
        source=ConnectionSource.REPOSITORY,
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
            "a2a_handler.tui.workspace.load_connection_catalog",
            return_value=ConnectionCatalog(repository_connections=(repo_connection,)),
        ),
        patch(
            "a2a_handler.tui.workspace.build_http_client",
            return_value=new_http_client,
        ),
        patch("a2a_handler.tui.workspace.A2AService") as mock_service_cls,
        patch("a2a_handler.tui.workspace.uuid.uuid4", return_value=fresh_context),
    ):
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        async with app.run_test() as pilot:
            await pilot.pause()

            workspace = app.query_one(WorkspaceTabs).get_active_workspace()
            assert workspace is not None

            connect_view = workspace.query_one(RemoteConnectView)
            connect_view.set_launch_mode(WorkspaceLaunchMode.START_FRESH)
            await workspace.handle_connect_button()
            await pilot.pause()

            assert workspace.current_context_id == str(fresh_context)
            patch_workspace_sources.set_conversation.assert_called_with(
                "https://agent.example.com",
                str(fresh_context),
                None,
            )


@pytest.mark.asyncio
async def test_connect_uses_selected_connection_default_auth() -> None:
    """Connect should use the selected connection's default auth when requested."""
    repo_connection = _make_connection(
        source=ConnectionSource.REPOSITORY,
        name="staging",
        agent_url="https://staging.example.com",
        auth=ConnectionAuthConfig(auth_type=AuthType.BEARER, value="profile-token"),
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.workspace.load_connection_catalog",
            return_value=ConnectionCatalog(repository_connections=(repo_connection,)),
        ),
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

            await workspace.handle_connect_button()
            await pilot.pause()

            credentials = mock_build_http_client.call_args.kwargs["credentials"]
            assert credentials is not None
            assert credentials.auth_type == AuthType.BEARER
            assert credentials.value == "profile-token"
            assert (
                workspace.state.auth_source == "repository connection 'staging' default"
            )


@pytest.mark.asyncio
async def test_connect_manual_override_uses_manual_credentials() -> None:
    """Explicit auth override should replace any connection default auth."""
    repo_connection = _make_connection(
        source=ConnectionSource.REPOSITORY,
        name="staging",
        agent_url="https://staging.example.com",
        auth=ConnectionAuthConfig(auth_type=AuthType.BEARER, value="profile-token"),
    )
    app = HandlerTUI()
    new_http_client = AsyncMock()
    mock_card = Mock()
    mock_card.name = "Demo Agent"
    mock_card.model_dump.return_value = {"name": "Demo Agent"}

    with (
        patch(
            "a2a_handler.tui.workspace.load_connection_catalog",
            return_value=ConnectionCatalog(repository_connections=(repo_connection,)),
        ),
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
            connect_view.set_auth_mode(WorkspaceAuthMode.OVERRIDE)
            connect_view.set_auth_credentials(create_bearer_auth("manual-token"))
            await workspace.handle_connect_button()
            await pilot.pause()

            credentials = mock_build_http_client.call_args.kwargs["credentials"]
            assert credentials is not None
            assert credentials.auth_type == AuthType.BEARER
            assert credentials.value == "manual-token"
            assert workspace.state.auth_source == "manual override"


@pytest.mark.asyncio
async def test_connect_transitions_workspace_to_live_view_and_updates_tab_title() -> (
    None
):
    """Successful connect should update the unified workspace view and tab title."""
    repo_connection = _make_connection(
        source=ConnectionSource.REPOSITORY,
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
            "a2a_handler.tui.workspace.load_connection_catalog",
            return_value=ConnectionCatalog(repository_connections=(repo_connection,)),
        ),
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

            await workspace.handle_connect_button()
            await pilot.pause()

            assert workspace.is_connected
            assert workspace.current_agent_url == "https://agent.example.com"
            assert workspace.query_one(RemoteLiveView)

            live_view = workspace.query_one(RemoteLiveView)
            messages_panel = live_view.query_one(TabbedMessagesPanel)
            connect_status = workspace.query_one("#connect-status", Static)
            tabs = app.query_one("#workspace-tabs", Tabs)
            first_tab = tabs.query_one("#workspace-tab-1", Tab)

            assert first_tab.label_text == "Demo Agent"
            assert messages_panel
            assert len(list(live_view.query("#workspace-summary"))) == 0
            assert "Connected" in str(connect_status.content)
            assert "Demo Agent" in str(connect_status.content)
            assert connect_status.has_class("status-success")
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

        workspace = app.query_one(WorkspaceTabs).get_active_workspace()
        assert workspace is not None

        connect_view = workspace.query_one(RemoteConnectView)
        connect_view.activate_source(ConnectionSource.MANUAL)
        connect_view.query_one("#manual-agent-url").value = "not-a-url"
        workspace._refresh_connect_selection()
        await workspace.handle_connect_button()
        await pilot.pause()

        status = connect_view.query_one("#connect-status", Static)

        assert "valid http(s) URL" in str(status.content)


def test_resolve_connection_credentials_uses_connection_default_auth() -> None:
    workspace = RemoteWorkspace(workspace_id="workspace-test", title="Remote Test")
    connection = _make_connection(
        source=ConnectionSource.REPOSITORY,
        name="staging",
        agent_url="https://staging.example.com",
        auth=ConnectionAuthConfig(auth_type=AuthType.BEARER, value="profile-token"),
    )
    workspace._connection_credentials = {
        connection.connection_id: create_bearer_auth("profile-token")
    }

    credentials, source, warning = workspace._resolve_connection_credentials(
        selected_connection=connection,
        active_source=ConnectionSource.REPOSITORY,
        auth_mode=WorkspaceAuthMode.USE_CONNECTION_DEFAULT,
        override_credentials=None,
    )

    assert credentials is not None
    assert credentials.value == "profile-token"
    assert source == "repository connection 'staging' default"
    assert warning is None


def test_resolve_connection_credentials_uses_manual_override() -> None:
    workspace = RemoteWorkspace(workspace_id="workspace-test", title="Remote Test")
    manual = create_bearer_auth("manual-token")

    credentials, source, warning = workspace._resolve_connection_credentials(
        selected_connection=None,
        active_source=ConnectionSource.MANUAL,
        auth_mode=WorkspaceAuthMode.OVERRIDE,
        override_credentials=manual,
    )

    assert credentials == manual
    assert source == "manual override"
    assert warning is None
