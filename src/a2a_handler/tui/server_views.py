"""Server connection and live server view components."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Input, Select, Static

from a2a_handler.auth import AuthCredentials
from a2a_handler.servers import ServerDefinition, ServerSource, server_source_label
from a2a_handler.tui.components import AgentCardPanel, InputPanel, TabbedMessagesPanel
from a2a_handler.tui.server_types import (
    MANUAL_SERVER_ID,
    summarize_identifier,
)

CONFIGURED_SERVER_SOURCES = (
    ServerSource.REPOSITORY,
    ServerSource.GLOBAL,
    ServerSource.RECENT,
)


class ServerConnectView(Container):
    """Compact connection bar for selecting and opening a server."""

    def __init__(self, server_title: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._server_title = server_title
        self._servers_by_id: dict[str, ServerDefinition] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-shell"):
            with Horizontal(id="server-bar"):
                yield Select(
                    [("Choose a server...", Select.BLANK)],
                    allow_blank=True,
                    id="server-select",
                )
                yield Input(
                    placeholder="http://localhost:8000",
                    value="http://localhost:8000",
                    id="manual-agent-url",
                    classes="hidden",
                )
                yield Button("CONNECT", id="connect-btn")
            yield Static(
                "Disconnected",
                id="server-status-row",
                classes="status-badge status-live",
            )

    def on_mount(self) -> None:
        status = self.query_one("#server-status-row", Static)
        status.add_class("status-info")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Press connect when the URL input is submitted."""
        connect_button = self.query_one("#connect-btn", Button)
        self.post_message(Button.Pressed(connect_button))

    def _messages_panel(self) -> TabbedMessagesPanel:
        for ancestor in self.ancestors:
            if isinstance(ancestor, ServerLiveView):
                return ancestor.messages_panel()
        raise LookupError("Connection bar is not mounted inside a server view")

    def set_server_catalog(
        self,
        repository_servers: tuple[ServerDefinition, ...],
        global_servers: tuple[ServerDefinition, ...],
        recent_servers: tuple[ServerDefinition, ...],
    ) -> None:
        """Populate the single flat select with grouped server options."""
        self._servers_by_id = {
            server_def.server_id: server_def
            for server_def in (
                *repository_servers,
                *global_servers,
                *recent_servers,
            )
        }

        options: list[tuple[str, str]] = []
        for source in CONFIGURED_SERVER_SOURCES:
            servers = {
                ServerSource.REPOSITORY: repository_servers,
                ServerSource.GLOBAL: global_servers,
                ServerSource.RECENT: recent_servers,
            }[source]
            if servers:
                group_label = server_source_label(source)
                for server_def in servers:
                    options.append(
                        (f"[{group_label}] {server_def.label}", server_def.server_id)
                    )

        options.append(("─── Enter URL manually...", MANUAL_SERVER_ID))

        select = self.query_one("#server-select", Select)
        select.set_options(options)

        if len(options) > 1:
            with self.prevent(Select.Changed):
                select.value = options[0][1]

    def _is_manual_selected(self) -> bool:
        select = self.query_one("#server-select", Select)
        return str(select.value) == MANUAL_SERVER_ID

    def _sync_manual_input(self) -> None:
        manual_input = self.query_one("#manual-agent-url", Input)
        if self._is_manual_selected():
            manual_input.remove_class("hidden")
        else:
            manual_input.add_class("hidden")

    def get_selected_server(self) -> ServerDefinition | None:
        """Return the currently selected configured server, if any."""
        select = self.query_one("#server-select", Select)
        if select.value == Select.BLANK:
            return None
        selected_value = str(select.value)
        if selected_value == MANUAL_SERVER_ID:
            return None
        return self._servers_by_id.get(selected_value)

    def get_url(self) -> str:
        """Get the current agent URL from the active selection."""
        if self._is_manual_selected():
            return self.query_one("#manual-agent-url", Input).value.strip()
        server_def = self.get_selected_server()
        return server_def.agent_url if server_def else ""

    def set_status(self, message: str, tone: str | None = None) -> None:
        """Update the status row."""
        display_message = message or "Disconnected"
        badge = self.query_one("#server-status-row", Static)
        badge.update(display_message)
        badge.remove_class("status-info")
        badge.remove_class("status-success")
        badge.remove_class("status-warning")
        badge.remove_class("status-error")
        if display_message == "Disconnected" and tone is None:
            tone = "info"
        if tone in {"info", "success", "warning", "error"}:
            badge.add_class(f"status-{tone}")

    def set_connected_status(
        self,
        agent_name: str,
        context_id: str | None = None,
    ) -> None:
        """Show the currently live connection state in the status row."""
        message = f"Connected · {agent_name}"
        if context_id:
            message = f"{message} · {summarize_identifier(context_id)}"
        self.set_status(message, tone="success")

    def set_status_line(self, text: str) -> None:
        """Set the single status row text."""
        self.query_one("#server-status-row", Static).update(text)

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
