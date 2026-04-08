"""Handler TUI application.

Provides an interactive terminal interface for communicating with A2A agents.
"""

from a2a_handler.tui.app import HandlerTUI, main
from a2a_handler.tui.server.tab import ServerTab
from a2a_handler.tui.server.tabs import ServerTabs

__all__ = ["HandlerTUI", "ServerTab", "ServerTabs", "main"]
