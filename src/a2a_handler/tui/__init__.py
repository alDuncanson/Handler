"""Handler TUI application.

Provides an interactive terminal interface for communicating with A2A agents.
"""

from a2a_handler.tui.app import HandlerTUI, main
from a2a_handler.tui.workspace import RemoteWorkspace, WorkspaceTabs

__all__ = ["HandlerTUI", "RemoteWorkspace", "WorkspaceTabs", "main"]
