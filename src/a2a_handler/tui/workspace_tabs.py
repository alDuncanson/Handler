"""Top-level workspace tab management."""

from __future__ import annotations

from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message as TextualMessage
from textual.widgets import Button, ContentSwitcher, Tab, Tabs

from a2a_handler.tui.remote_workspace import RemoteWorkspace


class WorkspaceTabs(Container):
    """Top-level workspace shell managing multiple remote workspaces."""

    class WorkspaceAdded(TextualMessage):
        """Posted when a workspace is added to the shell."""

        def __init__(self, workspace: RemoteWorkspace) -> None:
            super().__init__()
            self.workspace = workspace

    def __init__(self, initial_bearer_token: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._initial_bearer_token = initial_bearer_token
        self._workspace_count = 0
        self._tab_ids_by_workspace_id: dict[str, str] = {}
        self._workspace_ids_by_tab_id: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-shell"):
            with Horizontal(id="workspace-tab-row"):
                yield Tabs(id="workspace-tabs")
                yield Button("+ New Remote", id="new-workspace-btn")
            yield ContentSwitcher(id="workspace-content")

    async def on_mount(self) -> None:
        self.query_one("#workspace-tabs", Tabs).can_focus = False
        self.query_one("#new-workspace-btn", Button).can_focus = False
        await self.create_workspace(initial_bearer_token=self._initial_bearer_token)

    def iter_workspaces(self) -> list[RemoteWorkspace]:
        return list(self.query(RemoteWorkspace))

    def get_active_workspace(self) -> RemoteWorkspace | None:
        tabs = self.query_one("#workspace-tabs", Tabs)
        active_tab_id = tabs.active
        if not active_tab_id:
            return None

        workspace_id = self._workspace_ids_by_tab_id.get(active_tab_id)
        if workspace_id is None:
            return None

        try:
            return self.query_one(f"#{workspace_id}", RemoteWorkspace)
        except Exception:
            return None

    async def create_workspace(
        self,
        initial_bearer_token: str | None = None,
    ) -> RemoteWorkspace:
        self._workspace_count += 1
        workspace_title = f"Remote {self._workspace_count}"
        workspace_id = f"workspace-{self._workspace_count}"
        tab_id = f"workspace-tab-{self._workspace_count}"

        workspace = RemoteWorkspace(
            workspace_id=workspace_id,
            title=workspace_title,
            initial_bearer_token=initial_bearer_token,
        )

        self._tab_ids_by_workspace_id[workspace_id] = tab_id
        self._workspace_ids_by_tab_id[tab_id] = workspace_id

        switcher = self.query_one("#workspace-content", ContentSwitcher)
        tabs = self.query_one("#workspace-tabs", Tabs)

        with self.app.batch_update():
            await switcher.mount(workspace)
            await tabs.add_tab(Tab(workspace_title, id=tab_id, classes="workspace-tab"))
            tabs.active = tab_id
            switcher.current = workspace_id

        self.post_message(self.WorkspaceAdded(workspace))
        return workspace

    @on(Button.Pressed, "#new-workspace-btn")
    async def _handle_new_workspace(self) -> None:
        await self.create_workspace()

    @on(Tabs.TabActivated, "#workspace-tabs")
    def _handle_workspace_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab_id = event.tab.id
        if tab_id is None:
            return
        workspace_id = self._workspace_ids_by_tab_id.get(tab_id)
        if workspace_id is None:
            return
        self.query_one("#workspace-content", ContentSwitcher).current = workspace_id

    @on(RemoteWorkspace.TitleChanged)
    def _handle_workspace_title_changed(
        self, event: RemoteWorkspace.TitleChanged
    ) -> None:
        tab_id = self._tab_ids_by_workspace_id.get(event.workspace_id)
        if tab_id is None:
            return
        tab = self.query_one(f"#{tab_id}", Tab)
        tab.label = event.title

    async def close_workspace(self, workspace_id: str | None = None) -> None:
        """Close and remove a workspace tab. Defaults to the active workspace."""
        if workspace_id is None:
            active = self.get_active_workspace()
            if active is None:
                return
            workspace_id = active.workspace_id

        tab_id = self._tab_ids_by_workspace_id.get(workspace_id)
        if tab_id is None:
            return

        if len(self._workspace_ids_by_tab_id) <= 1:
            return

        tabs = self.query_one("#workspace-tabs", Tabs)
        switcher = self.query_one("#workspace-content", ContentSwitcher)
        workspace = self.query_one(f"#{workspace_id}", RemoteWorkspace)

        with self.app.batch_update():
            await tabs.remove_tab(tab_id)
            await workspace.remove()

        del self._tab_ids_by_workspace_id[workspace_id]
        del self._workspace_ids_by_tab_id[tab_id]

        active_tab_id = tabs.active
        if active_tab_id:
            new_workspace_id = self._workspace_ids_by_tab_id.get(active_tab_id)
            if new_workspace_id:
                switcher.current = new_workspace_id

    def action_previous_workspace(self) -> None:
        self.query_one("#workspace-tabs", Tabs).action_previous_tab()

    def action_next_workspace(self) -> None:
        self.query_one("#workspace-tabs", Tabs).action_next_tab()
