"""Command palette command construction for the TUI."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from textual.app import SystemCommand

from a2a_handler.tui.server.tabs import ServerTabs

if TYPE_CHECKING:
    from a2a_handler.tui.app import HandlerTUI


def iter_custom_system_commands(app: "HandlerTUI") -> Iterable[SystemCommand]:
    """Yield app-specific command palette entries."""
    server_tabs = app.query_one(ServerTabs)
    active = server_tabs.get_active_server()

    if active is not None and not active.is_connected:
        yield SystemCommand(
            "Connect",
            "Connect the active server using the selected server or recent session",
            app.action_connect_server,
        )

    if active is not None and active.is_connected:
        yield SystemCommand(
            "Reconnect",
            "Reconnect the active server using the selected server or recent session",
            app.action_reconnect_server,
        )
        yield SystemCommand(
            "Start Fresh Conversation",
            "Clear the current context and task while staying connected",
            app.action_start_fresh_conversation,
        )
        yield SystemCommand(
            "Attach File",
            "Queue a file path or URL to send with the next message",
            app.action_attach_file,
        )

    saved_session_target = (
        active.get_saved_session_target() if active is not None else None
    )
    if saved_session_target is not None:
        _, target_label = saved_session_target
        yield SystemCommand(
            "Forget Saved Session",
            f"Forget the saved recent session for '{target_label}'",
            app.action_forget_saved_session,
        )

    workspace_server = (
        active.get_selected_workspace_server() if active is not None else None
    )
    if workspace_server is not None and workspace_server.name:
        yield SystemCommand(
            "Rename Saved Workspace Server",
            f"Rename '{workspace_server.name}' in this repo's .handler/servers.toml",
            app.action_rename_workspace_server,
        )
        yield SystemCommand(
            "Remove Saved Workspace Server",
            (
                f"Remove '{workspace_server.name}' from this repo's "
                ".handler/servers.toml without closing the live tab"
            ),
            app.action_remove_workspace_server,
        )

    if active is not None and len(server_tabs.iter_servers()) > 1:
        yield SystemCommand(
            f"Close {active.title}",
            "Close the active server tab",
            app.action_close_server,
        )

    connected = [server for server in server_tabs.iter_servers() if server.is_connected]
    if connected:
        yield SystemCommand(
            "Git Add Servers",
            "Add connected servers to this repo's .handler/servers.toml",
            app.action_save_connections,
        )

    for server in server_tabs.iter_servers():
        if active is not None and server is active:
            continue
        yield SystemCommand(
            f"Switch to {server.title}",
            f"Activate the {server.title} server tab",
            app.switch_to_server_callback(server.server_id),
        )
