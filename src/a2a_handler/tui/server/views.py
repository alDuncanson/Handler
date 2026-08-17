"""Server connection and live server view components."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Input, Select, Static

from a2a_handler.servers import (
    ServerDefinition,
    ServerSource,
)
from a2a_handler.tui.components import AgentCardPanel, InputPanel, TabbedMessagesPanel
from a2a_handler.tui.server.types import MANUAL_SERVER_ID

CONFIGURED_SERVER_SOURCES = (
    ServerSource.REPOSITORY,
    ServerSource.GLOBAL,
    ServerSource.RECENT,
)
PICKER_GROUP_LABELS = {
    ServerSource.REPOSITORY: "Repository",
    ServerSource.GLOBAL: "User",
    ServerSource.RECENT: "Recent",
}
MANUAL_SERVER_LABEL = "URL..."


def _picker_option_label(server_def: ServerDefinition) -> str:
    """Build a plain-text picker label that stays readable in Textual selects."""
    source_label = PICKER_GROUP_LABELS[server_def.source]
    if server_def.source == ServerSource.RECENT:
        return f"{source_label}: {server_def.label} (resume)"
    return f"{source_label}: {server_def.label}"


class ConnectionBar(Container):
    """Compact connection bar for selecting and opening a server."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._servers_by_id: dict[str, ServerDefinition] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-shell"):
            with Horizontal(id="server-bar"):
                yield Select(
                    [("Choose a server or URL...", Select.BLANK)],
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
            with Horizontal(id="server-status-row"):
                yield Static(
                    "● Disconnected",
                    id="badge-status",
                    classes="conn-badge badge-muted",
                )
                yield Static("", id="badge-agent", classes="conn-badge hidden")
                yield Static("", id="badge-version", classes="conn-badge hidden")
                yield Static("", id="badge-source", classes="conn-badge hidden")
                yield Static("", id="badge-auth", classes="conn-badge hidden")
                yield Static("", id="badge-protocol", classes="conn-badge hidden")
                yield Static("", id="badge-transport", classes="conn-badge hidden")

    def on_mount(self) -> None:
        for widget in self.query("#server-status-row"):
            widget.can_focus = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Press connect when the URL input is submitted."""
        connect_button = self.query_one("#connect-btn", Button)
        self.post_message(Button.Pressed(connect_button))

    def set_connect_button_state(self, is_connected: bool) -> None:
        """Update the connect button label and tone for reconnect flows."""
        connect_button = self.query_one("#connect-btn", Button)
        connect_button.label = "RECONNECT" if is_connected else "CONNECT"
        if is_connected:
            connect_button.add_class("reconnect")
        else:
            connect_button.remove_class("reconnect")

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
                for server_def in servers:
                    options.append(
                        (_picker_option_label(server_def), server_def.server_id)
                    )

        options.append((MANUAL_SERVER_LABEL, MANUAL_SERVER_ID))

        select = self.query_one("#server-select", Select)
        select.set_options(options)

        with self.prevent(Select.Changed):
            if len(options) == 1:
                select.value = MANUAL_SERVER_ID
            else:
                select.value = options[0][1]
        self._sync_manual_input()

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
        """Return the currently selected picker entry, if any."""
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

    def _set_badge(
        self, badge_id: str, text: str, css_class: str | None = None
    ) -> None:
        """Show a badge with text and style, or hide it if text is empty."""
        badge = self.query_one(f"#{badge_id}", Static)
        if not text:
            badge.add_class("hidden")
            return
        badge.update(text)
        badge.remove_class("hidden", "badge-muted", "badge-success")
        if css_class:
            badge.add_class(css_class)

    def set_status(self, message: str, tone: str | None = None) -> None:
        """Update the status badge text (used for transient messages)."""
        status = self.query_one("#badge-status", Static)
        status.update(message or "● Disconnected")
        status.remove_class("badge-accent", "badge-muted", "badge-success")
        status.add_class("badge-muted" if tone is None else "badge-accent")

    def set_connected_status(
        self,
        agent_name: str,
        source_label: str = "",
        auth_label: str = "",
        protocol_version: str | None = None,
        agent_version: str | None = None,
        transport_label: str = "",
    ) -> None:
        """Show connection info as individual badges."""
        self.set_connect_button_state(True)
        self._set_badge("badge-status", "● Connected", "badge-success")
        self._set_badge("badge-agent", agent_name)
        self._set_badge("badge-source", source_label)
        self._set_badge("badge-auth", auth_label)
        self._set_badge(
            "badge-protocol",
            f"A2A v{protocol_version}" if protocol_version else "",
        )
        self._set_badge(
            "badge-version",
            f"v{agent_version}" if agent_version else "",
        )
        self._set_badge("badge-transport", transport_label)

    def show_disconnected_badges(self) -> None:
        """Reset badges to disconnected state."""
        self.set_connect_button_state(False)
        self._set_badge("badge-status", "● Disconnected", "badge-muted")
        self._set_badge("badge-agent", "")
        self._set_badge("badge-source", "")
        self._set_badge("badge-auth", "")
        self._set_badge("badge-protocol", "")
        self._set_badge("badge-version", "")
        self._set_badge("badge-transport", "")


class ServerView(Container):
    """Always-mounted server view with a compact connection bar."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        with Vertical(id="server-stage"):
            yield ConnectionBar()
            with Container(id="live-stage", classes="server-live-layout"):
                with Vertical(id="server-meta"):
                    yield AgentCardPanel(id="agent-card-container", classes="panel")

                with Vertical(id="server-main"):
                    yield TabbedMessagesPanel(id="messages-container", classes="panel")
                    yield InputPanel(id="input-container", classes="panel")

    def on_mount(self) -> None:
        connect_shell = self.query_one("#connect-shell")
        connect_shell.border_subtitle = "Server"
        self.query_one(
            "#agent-card-container", AgentCardPanel
        ).border_title = "Agent Card"
        self.query_one(
            "#messages-container", TabbedMessagesPanel
        ).border_subtitle = "Activity"
        self.query_one("#input-container", InputPanel).border_title = "Compose"
        self.input_panel().set_enabled(False)

    def connection_bar(self) -> ConnectionBar:
        return self.query_one(ConnectionBar)

    def agent_card_panel(self) -> AgentCardPanel:
        return self.query_one("#agent-card-container", AgentCardPanel)

    def messages_panel(self) -> TabbedMessagesPanel:
        return self.query_one("#messages-container", TabbedMessagesPanel)

    def input_panel(self) -> InputPanel:
        return self.query_one("#input-container", InputPanel)

    async def reset_session(self) -> None:
        await self.messages_panel().reset_session()
        self.agent_card_panel().update_card(None)
        self.input_panel().set_enabled(False)
