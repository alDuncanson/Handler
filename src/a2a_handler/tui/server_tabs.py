"""Top-level server tab management."""

from __future__ import annotations

from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message as TextualMessage
from textual.widgets import Button, ContentSwitcher, Tab, Tabs

from a2a_handler.tui.server_tab import ServerTab


class ServerTabs(Container):
    """Top-level server shell managing multiple server tabs."""

    class ServerAdded(TextualMessage):
        """Posted when a server is added to the shell."""

        def __init__(self, server: ServerTab) -> None:
            super().__init__()
            self.server = server

    def __init__(
        self,
        initial_bearer_token: str | None = None,
        connect_servers: tuple[str, ...] | None = None,
        connect_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._initial_bearer_token = initial_bearer_token
        self._connect_servers = connect_servers
        self._connect_url = connect_url
        self._server_count = 0
        self._tab_ids_by_server_id: dict[str, str] = {}
        self._server_ids_by_tab_id: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="server-shell"):
            with Horizontal(id="server-tab-row"):
                yield Tabs(id="server-tabs")
                yield Button("+ New Server", id="new-server-btn")
            yield ContentSwitcher(id="server-content")

    async def on_mount(self) -> None:
        self.query_one("#server-tabs", Tabs).can_focus = False
        self.query_one("#new-server-btn", Button).can_focus = False

        if self._connect_servers:
            for server_name in self._connect_servers:
                await self.create_server(
                    initial_bearer_token=self._initial_bearer_token,
                    auto_connect_server=server_name,
                )
        elif self._connect_url:
            await self.create_server(
                initial_bearer_token=self._initial_bearer_token,
                auto_connect_url=self._connect_url,
            )
        else:
            await self.create_server(initial_bearer_token=self._initial_bearer_token)

    def iter_servers(self) -> list[ServerTab]:
        return list(self.query(ServerTab))

    def get_active_server(self) -> ServerTab | None:
        tabs = self.query_one("#server-tabs", Tabs)
        active_tab_id = tabs.active
        if not active_tab_id:
            return None

        server_id = self._server_ids_by_tab_id.get(active_tab_id)
        if server_id is None:
            return None

        try:
            return self.query_one(f"#{server_id}", ServerTab)
        except Exception:
            return None

    async def create_server(
        self,
        initial_bearer_token: str | None = None,
        auto_connect_server: str | None = None,
        auto_connect_url: str | None = None,
    ) -> ServerTab:
        self._server_count += 1
        server_title = auto_connect_server or f"Server {self._server_count}"
        server_id = f"server-{self._server_count}"
        tab_id = f"server-tab-{self._server_count}"

        server = ServerTab(
            server_id=server_id,
            title=server_title,
            initial_bearer_token=initial_bearer_token,
            auto_connect_server=auto_connect_server,
            auto_connect_url=auto_connect_url,
        )

        self._tab_ids_by_server_id[server_id] = tab_id
        self._server_ids_by_tab_id[tab_id] = server_id

        switcher = self.query_one("#server-content", ContentSwitcher)
        tabs = self.query_one("#server-tabs", Tabs)

        with self.app.batch_update():
            await switcher.mount(server)
            await tabs.add_tab(Tab(server_title, id=tab_id, classes="server-tab"))
            tabs.active = tab_id
            switcher.current = server_id

        self.post_message(self.ServerAdded(server))
        return server

    @on(Button.Pressed, "#new-server-btn")
    async def _handle_new_server(self) -> None:
        await self.create_server()

    @on(Tabs.TabActivated, "#server-tabs")
    def _handle_server_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab_id = event.tab.id
        if tab_id is None:
            return
        server_id = self._server_ids_by_tab_id.get(tab_id)
        if server_id is None:
            return
        self.query_one("#server-content", ContentSwitcher).current = server_id

    @on(ServerTab.TitleChanged)
    def _handle_server_title_changed(
        self, event: ServerTab.TitleChanged
    ) -> None:
        tab_id = self._tab_ids_by_server_id.get(event.server_id)
        if tab_id is None:
            return
        tab = self.query_one(f"#{tab_id}", Tab)
        tab.label = event.title

    async def close_server(self, server_id: str | None = None) -> None:
        """Close and remove a server tab. Defaults to the active server."""
        if server_id is None:
            active = self.get_active_server()
            if active is None:
                return
            server_id = active.server_id

        tab_id = self._tab_ids_by_server_id.get(server_id)
        if tab_id is None:
            return

        if len(self._server_ids_by_tab_id) <= 1:
            return

        tabs = self.query_one("#server-tabs", Tabs)
        switcher = self.query_one("#server-content", ContentSwitcher)
        server = self.query_one(f"#{server_id}", ServerTab)

        with self.app.batch_update():
            await tabs.remove_tab(tab_id)
            await server.remove()

        del self._tab_ids_by_server_id[server_id]
        del self._server_ids_by_tab_id[tab_id]

        active_tab_id = tabs.active
        if active_tab_id:
            new_server_id = self._server_ids_by_tab_id.get(active_tab_id)
            if new_server_id:
                switcher.current = new_server_id

    def action_previous_server(self) -> None:
        self.query_one("#server-tabs", Tabs).action_previous_tab()

    def action_next_server(self) -> None:
        self.query_one("#server-tabs", Tabs).action_next_tab()
