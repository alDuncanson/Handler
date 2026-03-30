"""Server connection and live server view components."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Input, Select, Static

from a2a_handler.auth import AuthCredentials
from a2a_handler.servers import ServerDefinition, ServerSource
from a2a_handler.tui.components import AgentCardPanel, InputPanel, TabbedMessagesPanel
from a2a_handler.tui.server_types import (
    AUTH_MODE_OPTIONS,
    EMPTY_SERVER_ID,
    EMPTY_SOURCE_LABELS,
    SAVED_SESSION_OPTIONS,
    SOURCE_OPTIONS,
    START_FRESH_OPTION,
    SavedConversation,
    ServerAuthMode,
    ServerLaunchMode,
    summarize_identifier,
)


class ServerConnectView(Container):
    """Compact connection bar for selecting and opening a server."""

    def __init__(self, server_title: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._server_title = server_title
        self._servers_by_id: dict[str, ServerDefinition] = {}
        self._servers_by_source: dict[
            ServerSource, tuple[ServerDefinition, ...]
        ] = {
            ServerSource.REPOSITORY: (),
            ServerSource.GLOBAL: (),
            ServerSource.RECENT: (),
        }
        self._selected_server_ids: dict[ServerSource, str] = {}
        self._active_source = ServerSource.REPOSITORY

    def compose(self) -> ComposeResult:
        with Vertical(id="connection-shell"):
            with Horizontal(id="connection-bar"):
                yield Select(
                    SOURCE_OPTIONS,
                    allow_blank=False,
                    value=ServerSource.REPOSITORY.value,
                    id="connection-source-select",
                )
                yield Select(
                    [
                        (
                            EMPTY_SOURCE_LABELS[ServerSource.REPOSITORY],
                            EMPTY_SERVER_ID,
                        )
                    ],
                    allow_blank=False,
                    value=EMPTY_SERVER_ID,
                    id="connection-target-select",
                )
                yield Input(
                    placeholder="http://localhost:8000",
                    value="http://localhost:8000",
                    id="manual-agent-url",
                    classes="hidden",
                )
                yield Select(
                    START_FRESH_OPTION,
                    allow_blank=False,
                    value=ServerLaunchMode.START_FRESH.value,
                    id="launch-mode-select",
                )
                yield Select(
                    AUTH_MODE_OPTIONS,
                    allow_blank=False,
                    value=ServerAuthMode.USE_CONNECTION_DEFAULT.value,
                    id="auth-mode-select",
                )
                yield Button("CONNECT", id="connect-btn")
            with Horizontal(id="connection-meta-row"):
                yield Static(
                    "Repository",
                    id="connection-selection-status",
                    classes="status-badge status-connection",
                )
                yield Static(
                    "Fresh only",
                    id="conversation-status",
                    classes="status-badge status-conversation",
                )
                yield Static(
                    "Auth · none",
                    id="auth-source-status",
                    classes="status-badge status-auth",
                )
                yield Static(
                    "Disconnected",
                    id="connect-status",
                    classes="status-badge status-live",
                )

    def on_mount(self) -> None:
        self.sync_source_controls()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Press connect when the URL input is submitted."""
        connect_button = self.query_one("#connect-btn", Button)
        self.post_message(Button.Pressed(connect_button))

    def _messages_panel(self) -> TabbedMessagesPanel:
        for ancestor in self.ancestors:
            if isinstance(ancestor, ServerLiveView):
                return ancestor.messages_panel()
        raise LookupError("Connection bar is not mounted inside a server view")

    def sync_source_controls(self) -> None:
        """Keep the target dropdown and manual URL input in sync with the source."""
        source_value = self.query_one("#connection-source-select", Select).value
        active_source = ServerSource(str(source_value))
        if active_source != self._active_source:
            self._remember_active_selection()
            self._active_source = active_source

        target_select = self.query_one("#connection-target-select", Select)
        manual_input = self.query_one("#manual-agent-url", Input)
        if active_source == ServerSource.MANUAL:
            target_select.add_class("hidden")
            manual_input.remove_class("hidden")
            return

        target_select.remove_class("hidden")
        manual_input.add_class("hidden")
        self._set_target_options(active_source)

    def _remember_active_selection(self) -> None:
        if self._active_source == ServerSource.MANUAL:
            return
        target_select = self.query_one("#connection-target-select", Select)
        if target_select.value == Select.BLANK:
            return
        selected_value = str(target_select.value)
        if selected_value == EMPTY_SERVER_ID:
            return
        self._selected_server_ids[self._active_source] = selected_value

    def activate_source(self, source: ServerSource) -> None:
        """Activate a server source programmatically."""
        with self.prevent(Select.Changed):
            self.query_one("#connection-source-select", Select).value = source.value
        self.sync_source_controls()

    def get_active_source(self) -> ServerSource:
        """Return the currently selected server source."""
        source_value = self.query_one("#connection-source-select", Select).value
        return ServerSource(str(source_value))

    def set_server_catalog(
        self,
        repository_servers: tuple[ServerDefinition, ...],
        global_servers: tuple[ServerDefinition, ...],
        recent_servers: tuple[ServerDefinition, ...],
    ) -> None:
        """Populate the bar with explicit server options."""
        self._servers_by_id = {
            server_def.server_id: server_def
            for server_def in (
                *repository_servers,
                *global_servers,
                *recent_servers,
            )
        }
        self._servers_by_source = {
            ServerSource.REPOSITORY: repository_servers,
            ServerSource.GLOBAL: global_servers,
            ServerSource.RECENT: recent_servers,
        }
        self.sync_source_controls()

    def _set_target_options(self, source: ServerSource) -> None:
        servers = self._servers_by_source[source]
        select = self.query_one("#connection-target-select", Select)
        options = (
            [(server_def.label, server_def.server_id) for server_def in servers]
            if servers
            else [(EMPTY_SOURCE_LABELS[source], EMPTY_SERVER_ID)]
        )
        next_value = self._selected_server_ids.get(source, options[0][1])
        if not any(option_value == next_value for _, option_value in options):
            next_value = options[0][1]
        select.set_options(options)
        with self.prevent(Select.Changed):
            select.value = next_value

    def _set_badge(
        self,
        badge_id: str,
        text: str,
        tone: str | None = None,
    ) -> None:
        badge = self.query_one(f"#{badge_id}", Static)
        badge.update(text)
        badge.remove_class("status-info")
        badge.remove_class("status-success")
        badge.remove_class("status-warning")
        badge.remove_class("status-error")
        if tone in {"info", "success", "warning", "error"}:
            badge.add_class(f"status-{tone}")

    def set_selected_server_summary(self, summary: str) -> None:
        """Update the server badge shown below the bar."""
        self._set_badge("connection-selection-status", summary)

    def set_auth_source_status(
        self, source_description: str, tone: str | None = None
    ) -> None:
        """Update the auth-source badge shown below the bar."""
        self._set_badge("auth-source-status", f"Auth · {source_description}", tone)

    def get_launch_mode(self) -> ServerLaunchMode:
        launch_value = self.query_one("#launch-mode-select", Select).value
        if str(launch_value) == ServerLaunchMode.RESUME_SESSION.value:
            return ServerLaunchMode.RESUME_SESSION
        return ServerLaunchMode.START_FRESH

    def set_launch_mode(self, launch_mode: ServerLaunchMode) -> None:
        launch_select = self.query_one("#launch-mode-select", Select)
        with self.prevent(Select.Changed):
            try:
                launch_select.value = launch_mode.value
            except Exception:
                launch_select.value = ServerLaunchMode.START_FRESH.value

    def get_auth_mode(self) -> ServerAuthMode:
        auth_value = self.query_one("#auth-mode-select", Select).value
        if str(auth_value) == ServerAuthMode.OVERRIDE.value:
            return ServerAuthMode.OVERRIDE
        return ServerAuthMode.USE_CONNECTION_DEFAULT

    def set_auth_mode(self, auth_mode: ServerAuthMode) -> None:
        with self.prevent(Select.Changed):
            self.query_one("#auth-mode-select", Select).value = auth_mode.value

    def set_saved_conversation(
        self,
        conversation: SavedConversation | None,
        warning: str | None = None,
    ) -> None:
        launch_select = self.query_one("#launch-mode-select", Select)

        if warning:
            launch_select.set_options(START_FRESH_OPTION)
            self.set_launch_mode(ServerLaunchMode.START_FRESH)
            self._set_badge("conversation-status", warning, tone="warning")
            return

        if conversation is None:
            launch_select.set_options(START_FRESH_OPTION)
            self.set_launch_mode(ServerLaunchMode.START_FRESH)
            self._set_badge("conversation-status", "Fresh only")
            return

        launch_select.set_options(SAVED_SESSION_OPTIONS)
        task_suffix = ""
        if conversation.task_id:
            task_suffix = f" · task {summarize_identifier(conversation.task_id)}"
        self._set_badge(
            "conversation-status",
            "Resume available · "
            f"{summarize_identifier(conversation.context_id)}{task_suffix}",
            tone="info",
        )
        if self.get_launch_mode() == ServerLaunchMode.START_FRESH:
            self.set_launch_mode(ServerLaunchMode.RESUME_SESSION)

    def set_status(self, message: str, tone: str | None = None) -> None:
        """Update the live connection badge."""
        display_message = message or "Disconnected"
        if display_message == "Disconnected" and tone is None:
            tone = "info"
        self._set_badge("connect-status", display_message, tone)

    def set_connected_status(
        self,
        agent_name: str,
        context_id: str | None = None,
    ) -> None:
        """Show the currently live connection state in the status badge."""
        message = f"Connected · {agent_name}"
        if context_id:
            message = f"{message} · {summarize_identifier(context_id)}"
        self.set_status(message, tone="success")

    def get_selected_server(self) -> ServerDefinition | None:
        """Return the currently selected configured server, if any."""
        source = self.get_active_source()
        if source == ServerSource.MANUAL:
            return None

        select = self.query_one("#connection-target-select", Select)
        if select.value == Select.BLANK:
            return None
        selected_value = str(select.value)
        if selected_value == EMPTY_SERVER_ID:
            return None
        return self._servers_by_id.get(selected_value)

    def get_url(self) -> str:
        """Get the current agent URL from the active source selection."""
        active_source = self.get_active_source()
        if active_source == ServerSource.MANUAL:
            return self.query_one("#manual-agent-url", Input).value.strip()
        server_def = self.get_selected_server()
        return server_def.agent_url if server_def else ""

    def get_auth_credentials(self) -> AuthCredentials | None:
        return self._messages_panel().get_auth_credentials()

    def set_auth_credentials(self, credentials: AuthCredentials | None) -> None:
        self._messages_panel().set_auth_credentials(credentials)


class ServerLiveView(Container):
    """Always-mounted server view with a compact connection bar."""

    def __init__(self, server_title: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._server_title = server_title

    def compose(self) -> ComposeResult:
        with Vertical(id="server-stage"):
            yield ServerConnectView(self._server_title)
            with Container(id="live-stage", classes="server-live-layout"):
                with Vertical(id="server-meta"):
                    yield AgentCardPanel(id="agent-card-container", classes="panel")

                with Vertical(id="server-main"):
                    yield TabbedMessagesPanel(id="messages-container", classes="panel")
                    yield InputPanel(id="input-container", classes="panel")

    def on_mount(self) -> None:
        self.query_one(
            "#agent-card-container", AgentCardPanel
        ).border_title = "Agent Card"
        self.query_one(
            "#messages-container", TabbedMessagesPanel
        ).border_title = "Activity"
        self.query_one("#input-container", InputPanel).border_title = "Compose"
        self.input_panel().set_enabled(False)
        self.show_disconnected_state()

    def connect_view(self) -> ServerConnectView:
        return self.query_one(ServerConnectView)

    def agent_card_panel(self) -> AgentCardPanel:
        return self.query_one("#agent-card-container", AgentCardPanel)

    def messages_panel(self) -> TabbedMessagesPanel:
        return self.query_one("#messages-container", TabbedMessagesPanel)

    def input_panel(self) -> InputPanel:
        return self.query_one("#input-container", InputPanel)

    def show_disconnected_state(self) -> None:
        self.connect_view().set_status("Disconnected", tone="info")
        self.agent_card_panel().update_card(None)
        self.input_panel().set_enabled(False)

    async def prepare_for_connection(self) -> None:
        await self.messages_panel().reset_session()
        self.agent_card_panel().update_card(None)
        self.input_panel().set_enabled(False)
