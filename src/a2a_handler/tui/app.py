"""Main TUI application for Handler."""

import logging
from collections.abc import Iterable
from typing import Any

from textual import on
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.logging import TextualHandler
from textual.screen import Screen
from textual.widgets import Footer

from a2a_handler.common import get_theme, install_tui_log_handler, save_theme
from a2a_handler.common.logging import TUILogHandler
from a2a_handler.tui.components import AgentCardPanel, TabbedMessagesPanel
from a2a_handler.tui.workspace import WorkspaceTabs

logging.basicConfig(
    level="NOTSET",
    handlers=[TextualHandler()],
)
logger = logging.getLogger(__name__)


class HandlerTUI(App[Any]):
    """Handler - A2A Agent Management Interface."""

    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("/", "command_palette", "Palette", show=True),
        Binding("ctrl+m", "toggle_maximize", "Maximize", show=True),
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

    def __init__(self, initial_bearer_token: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._is_maximized: bool = False
        self._initial_bearer_token = initial_bearer_token
        self._tui_log_handler: TUILogHandler | None = None

    def compose(self) -> ComposeResult:
        yield WorkspaceTabs(initial_bearer_token=self._initial_bearer_token)
        yield Footer(show_command_palette=False)

    async def on_mount(self) -> None:
        logger.info("TUI application starting")
        self.theme = get_theme()
        self._tui_log_handler = install_tui_log_handler(level=logging.DEBUG)
        self._tui_log_handler.set_callback(self._on_log_line)

        workspace_tabs = self.query_one(WorkspaceTabs)
        for workspace in workspace_tabs.iter_workspaces():
            workspace.load_logs(self._tui_log_handler.get_lines())

    def _on_log_line(self, line: str) -> None:
        try:
            workspace_tabs = self.query_one(WorkspaceTabs)
        except Exception:
            return
        for workspace in workspace_tabs.iter_workspaces():
            workspace.add_log(line)

    @on(WorkspaceTabs.WorkspaceAdded)
    def _handle_workspace_added(self, event: WorkspaceTabs.WorkspaceAdded) -> None:
        if self._tui_log_handler is None:
            return
        event.workspace.load_logs(self._tui_log_handler.get_lines())

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

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Filter out maximize/minimize commands from the command palette."""
        for command in super().get_system_commands(screen):
            if command.title.lower() in ("maximize", "minimize"):
                continue
            yield command

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
