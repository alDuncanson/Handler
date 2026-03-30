"""Main TUI application for Handler."""

import logging
from collections.abc import Iterable
from typing import Any

from textual import on
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.logging import TextualHandler
from textual.screen import Screen
from textual.widgets import Footer, Tabs

from a2a_handler.common import get_theme, install_tui_log_handler, save_theme
from a2a_handler.common.logging import TUILogHandler
from a2a_handler.tui.components import AgentCardPanel, TabbedMessagesPanel
from a2a_handler.tui.server_tabs import ServerTabs

logging.basicConfig(
    level="NOTSET",
    handlers=[TextualHandler()],
)
logger = logging.getLogger(__name__)


class HandlerTUI(App[Any]):
    """Handler - A2A Agent Management Interface."""

    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding(
            "ctrl+c",
            "quit",
            "Quit",
            show=True,
            key_display="Ctrl+C",
            priority=True,
        ),
        Binding("ctrl+p", "command_palette", "Palette", show=True, key_display="Ctrl+P"),
        Binding("ctrl+m", "toggle_maximize", "Maximize", show=True),
        Binding(
            "ctrl+b",
            "previous_server",
            "Prev Server",
            show=True,
            key_display="Ctrl+B",
        ),
        Binding(
            "ctrl+t",
            "next_server",
            "Next Server",
            show=True,
            key_display="Ctrl+T",
        ),
        Binding(
            "ctrl+n", "new_server", "New Server", show=True, key_display="Ctrl+N"
        ),
        Binding(
            "ctrl+w",
            "close_server",
            "Close Server",
            show=True,
            key_display="Ctrl+W",
        ),
    ]

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Show maximize binding only for maximizable panels."""
        if action == "toggle_maximize":
            focused = self.focused
            if focused is None:
                return False
            for panel in [
                *self.query(TabbedMessagesPanel),
                *self.query(AgentCardPanel),
            ]:
                if focused is panel or panel in focused.ancestors:
                    return True
            return False
        return True

    def __init__(
        self,
        initial_bearer_token: str | None = None,
        connect_servers: tuple[str, ...] | None = None,
        connect_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._is_maximized: bool = False
        self._initial_bearer_token = initial_bearer_token
        self._connect_servers = connect_servers
        self._connect_url = connect_url
        self._tui_log_handler: TUILogHandler | None = None

    def compose(self) -> ComposeResult:
        yield ServerTabs(
            initial_bearer_token=self._initial_bearer_token,
            connect_servers=self._connect_servers,
            connect_url=self._connect_url,
        )
        yield Footer(show_command_palette=False)

    async def on_mount(self) -> None:
        logger.info("TUI application starting")
        self.theme = get_theme()
        self._tui_log_handler = install_tui_log_handler(level=logging.DEBUG)
        self._tui_log_handler.set_callback(self._on_log_line)

        server_tabs = self.query_one(ServerTabs)
        for server in server_tabs.iter_servers():
            server.load_logs(self._tui_log_handler.get_lines())

    def _on_log_line(self, line: str) -> None:
        try:
            server_tabs = self.query_one(ServerTabs)
        except Exception:
            return
        for server in server_tabs.iter_servers():
            server.add_log(line)

    @on(ServerTabs.ServerAdded)
    def _handle_server_added(self, event: ServerTabs.ServerAdded) -> None:
        if self._tui_log_handler is None:
            return
        event.server.load_logs(self._tui_log_handler.get_lines())

    def watch_theme(self, new_theme: str) -> None:
        """Called when the app theme changes."""
        logger.debug("Theme changed to: %s", new_theme)
        save_theme(new_theme)
        for agent_card_panel in self.query(AgentCardPanel):
            agent_card_panel.refresh_theme()

    def action_toggle_maximize(self) -> None:
        """Toggle maximize for the focused panel."""
        if self._is_maximized:
            self.screen.minimize()
            self._is_maximized = False
            return

        focused = self.focused
        if focused is None:
            return

        for panel in [*self.query(TabbedMessagesPanel), *self.query(AgentCardPanel)]:
            if focused is panel or panel in focused.ancestors:
                self.screen.maximize(panel)
                self._is_maximized = True
                return

    def action_previous_server(self) -> None:
        """Activate the previous server tab."""
        self.query_one(ServerTabs).action_previous_server()

    def action_next_server(self) -> None:
        """Activate the next server tab."""
        self.query_one(ServerTabs).action_next_server()

    async def action_new_server(self) -> None:
        """Create and activate a new server tab."""
        await self.query_one(ServerTabs).create_server()

    async def action_close_server(self) -> None:
        """Close the active server tab."""
        await self.query_one(ServerTabs).close_server()

    async def action_connect_server(self) -> None:
        """Trigger the connect button on the active server."""
        server = self.query_one(ServerTabs).get_active_server()
        if server is not None and not server.is_connected:
            await server.handle_connect_button()

    async def action_start_fresh(self) -> None:
        """Connect the active server without resuming any saved session."""
        server = self.query_one(ServerTabs).get_active_server()
        if server is not None and not server.is_connected:
            await server.handle_connect_button(force_fresh=True)

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Provide custom commands and filter out maximize/minimize."""
        for command in super().get_system_commands(screen):
            if command.title.lower() in ("maximize", "minimize"):
                continue
            yield command

        server_tabs = self.query_one(ServerTabs)
        active = server_tabs.get_active_server()

        if active is not None and not active.is_connected:
            yield SystemCommand(
                "Connect",
                "Connect the active server to an A2A agent",
                self.action_connect_server,
            )

        if active is not None and not active.is_connected:
            yield SystemCommand(
                "Start Fresh",
                "Connect without resuming any saved session",
                self.action_start_fresh,
            )

        if active is not None and len(server_tabs.iter_servers()) > 1:
            yield SystemCommand(
                f"Close {active.title}",
                "Close the active server tab",
                self.action_close_server,
            )

        for server in server_tabs.iter_servers():
            if active is not None and server is active:
                continue
            title = server.title
            yield SystemCommand(
                f"Switch to {title}",
                f"Activate the {title} server tab",
                self._switch_to_server(server.server_id),
            )

    def _switch_to_server(self, server_id: str) -> callable:
        """Return a callback that activates the given server tab."""
        def callback() -> None:
            server_tabs = self.query_one(ServerTabs)
            tab_id = server_tabs._tab_ids_by_server_id.get(server_id)
            if tab_id is not None:
                tabs = server_tabs.query_one("#server-tabs", Tabs)
                tabs.active = tab_id

        return callback

    async def on_unmount(self) -> None:
        if self._tui_log_handler is not None:
            self._tui_log_handler.set_callback(None)
        logger.info("Shutting down TUI application")


def main() -> None:
    """Entry point for the TUI application."""
    application = HandlerTUI()
    application.run()


if __name__ == "__main__":
    main()
