"""Main TUI application for Handler."""

import logging
from collections.abc import Callable, Iterable
from importlib.metadata import version
from typing import Any

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.containers import Horizontal
from textual.logging import TextualHandler
from textual.screen import Screen
from textual.widgets import HelpPanel, Static, Tabs

from a2a_handler.common import get_theme, install_tui_log_handler, save_theme
from a2a_handler.common.logging import TUILogHandler
from a2a_handler.tui.commands import (
    ConfirmScreen,
    TextPromptScreen,
    iter_custom_system_commands,
)
from a2a_handler.tui.components import AgentCardPanel, TabbedMessagesPanel
from a2a_handler.tui.server.save import save_connections_to_workspace
from a2a_handler.tui.server.tabs import ServerTabs
from a2a_handler.tui.server.workspace import (
    remove_workspace_server,
    rename_workspace_server,
)

logging.basicConfig(
    level="NOTSET",
    handlers=[TextualHandler()],
)
logger = logging.getLogger(__name__)
HANDLER_VERSION = version("a2a-handler")


def _footer_bindings_text() -> Text:
    """Return footer keybindings with chords visually distinct from actions."""
    return Text.assemble(
        ("Ctrl+Q", "bold yellow"),
        (" Quit  ", "dim"),
        ("Ctrl+P", "bold yellow"),
        (" Command Palette  ", "dim"),
        ("?", "bold yellow"),
        (" Keybindings", "dim"),
    )


class HandlerTUI(App[Any]):
    """Handler - A2A Agent Management Interface."""

    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding(
            "ctrl+q",
            "quit",
            "Quit",
            show=True,
            key_display="Ctrl+Q",
            priority=True,
        ),
        Binding(
            "ctrl+p",
            "command_palette",
            "Command Palette",
            show=True,
            key_display="Ctrl+P",
        ),
        Binding("?", "toggle_help_panel", "Keybindings", show=True),
        Binding("ctrl+m", "toggle_maximize", "Maximize", show=False),
        Binding(
            "ctrl+b",
            "previous_server",
            "Prev Server",
            show=False,
            key_display="Ctrl+B",
        ),
        Binding(
            "ctrl+t",
            "next_server",
            "Next Server",
            show=False,
            key_display="Ctrl+T",
        ),
        Binding("ctrl+n", "new_server", "New Server", show=False, key_display="Ctrl+N"),
        Binding(
            "ctrl+w",
            "close_server",
            "Close Server",
            show=False,
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
        with Horizontal(id="app-footer"):
            yield Static(
                _footer_bindings_text(),
                id="app-footer-bindings",
            )
            yield Static(f"v{HANDLER_VERSION}", id="app-version")

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

    def action_toggle_help_panel(self) -> None:
        """Toggle Textual's keybindings help panel."""
        try:
            self.screen.query_one(HelpPanel)
        except NoMatches:
            self.action_show_help_panel()
        else:
            self.action_hide_help_panel()

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
        """Connect the active server using the current picker selection."""
        server = self._get_active_server()
        if server is not None and not server.is_connected:
            await server.handle_connect_button()

    async def action_reconnect_server(self) -> None:
        """Reconnect the active server using the current picker selection."""
        server = self._get_active_server()
        if server is None or not server.is_connected:
            self.notify("Connect to a server before reconnecting", severity="warning")
            return
        await server.handle_connect_button()

    async def action_start_fresh_conversation(self) -> None:
        """Reset the active server to a fresh conversation context."""
        server = self._get_active_server()
        if server is None or not server.is_connected:
            self.notify("Connect to a server before starting fresh", severity="warning")
            return
        await server.start_fresh_conversation()

    def action_forget_saved_session(self) -> None:
        """Forget the saved session for the selected or active server URL."""
        server = self._get_active_server()
        session_target = server.get_saved_session_target() if server else None
        if session_target is None:
            self.notify(
                "Choose a recent session or connected server to forget",
                severity="warning",
            )
            return

        agent_url, target_label = session_target
        self.push_screen(
            ConfirmScreen(
                "Forget Saved Session",
                (
                    f"Forget the saved session for '{target_label}'? "
                    "The live tab will stay open."
                ),
                confirm_label="Forget",
            ),
            callback=lambda confirmed: self._handle_forget_saved_session_result(
                agent_url,
                target_label,
                confirmed,
            ),
        )

    def _handle_forget_saved_session_result(
        self,
        agent_url: str,
        target_label: str,
        confirmed: bool,
    ) -> None:
        """Apply a forget-session result after the confirmation screen is dismissed."""
        if not confirmed:
            return

        server = self._get_active_server()
        if server is None:
            return

        try:
            server.forget_saved_session(agent_url)
            self.notify(
                f"Forgot saved session for '{target_label}'. Live tab stays open."
            )
        except Exception as error:
            self.notify(f"Failed to forget saved session: {error}", severity="error")

    def action_rename_workspace_server(self) -> None:
        """Rename the selected repository-local workspace server."""
        server = self._get_active_server()
        workspace_server = server.get_selected_workspace_server() if server else None
        if workspace_server is None or workspace_server.name is None:
            self.notify("Choose a workspace server to rename", severity="warning")
            return

        self.push_screen(
            TextPromptScreen(
                "Rename Saved Workspace Server",
                "Update this repo's saved server name.",
                value=workspace_server.name,
                placeholder="workspace_server",
                confirm_label="Rename",
            ),
            callback=lambda new_name: self._handle_rename_workspace_server_result(
                workspace_server.name,
                new_name,
            ),
        )

    def _handle_rename_workspace_server_result(
        self,
        current_name: str,
        new_name: str | None,
    ) -> None:
        """Apply a rename result after the prompt screen is dismissed."""
        if new_name is None or new_name == current_name:
            return

        try:
            rename_workspace_server(current_name, new_name)
            self._refresh_server_catalogs()
            self.notify(f"Renamed saved workspace server to {new_name}")
        except Exception as error:
            self.notify(f"Failed to rename workspace server: {error}", severity="error")

    def action_remove_workspace_server(self) -> None:
        """Remove the selected repository-local workspace server."""
        server = self._get_active_server()
        workspace_server = server.get_selected_workspace_server() if server else None
        if workspace_server is None or workspace_server.name is None:
            self.notify("Choose a workspace server to remove", severity="warning")
            return

        self.push_screen(
            ConfirmScreen(
                "Remove Saved Workspace Server",
                (
                    f"Remove '{workspace_server.name}' from this repo's "
                    ".handler/servers.toml? The live tab will stay open until you close it."
                ),
                confirm_label="Remove",
            ),
            callback=lambda confirmed: self._handle_remove_workspace_server_result(
                workspace_server.name,
                confirmed,
            ),
        )

    def _handle_remove_workspace_server_result(
        self,
        current_name: str,
        confirmed: bool,
    ) -> None:
        """Apply a remove result after the confirmation screen is dismissed."""
        if not confirmed:
            return

        try:
            remove_workspace_server(current_name)
            self._refresh_server_catalogs()
            self.notify(
                f"Removed saved workspace server '{current_name}'. Live tab stays open."
            )
        except Exception as error:
            self.notify(f"Failed to remove workspace server: {error}", severity="error")

    async def action_save_connections(self) -> None:
        """Add current connections to this repo's .handler/servers.toml."""
        server_tabs = self.query_one(ServerTabs)
        connected = [s for s in server_tabs.iter_servers() if s.is_connected]
        if not connected:
            self.notify("No connected servers to add", severity="warning")
            return

        try:
            count = save_connections_to_workspace(connected)
            self.notify(f"Added {count} server(s) to .handler/servers.toml")
        except Exception as error:
            self.notify(f"Failed to save: {error}", severity="error")

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Provide custom commands and filter out maximize/minimize."""
        for command in super().get_system_commands(screen):
            if command.title.lower() in ("maximize", "minimize"):
                continue
            yield command

        yield from iter_custom_system_commands(self)

    def switch_to_server_callback(self, server_id: str) -> Callable[[], None]:
        """Return a callback that activates the given server tab."""

        def callback() -> None:
            server_tabs = self.query_one(ServerTabs)
            tab_id = server_tabs._tab_ids_by_server_id.get(server_id)
            if tab_id is not None:
                tabs = server_tabs.query_one("#server-tabs", Tabs)
                tabs.active = tab_id

        return callback

    def _get_active_server(self):
        return self.query_one(ServerTabs).get_active_server()

    def _refresh_server_catalogs(self) -> None:
        for server in self.query_one(ServerTabs).iter_servers():
            server.refresh_server_catalog()

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
