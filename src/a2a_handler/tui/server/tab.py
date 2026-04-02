"""Per-server tab controller."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Generator
from typing import Any

import httpx
from a2a.types import AgentCard, Message as A2AMessage, Role, Task
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message as TextualMessage
from textual.widgets import Button, Input, RadioSet, Select

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    validate_agent_url,
)
from a2a_handler.servers import (
    ServerCatalog,
    ServerDefinition,
    load_server_catalog,
    resolve_server_credentials,
)
from a2a_handler.service import (
    A2AService,
    extract_text_from_message_parts,
    response_context_id,
    response_task_id,
)
from a2a_handler.session import get_session_store
from a2a_handler.tui.components import TabbedMessagesPanel
from a2a_handler.tui.server.session import resolve_saved_conversation
from a2a_handler.tui.server.types import (
    MANUAL_SERVER_ID,
    RECENT_SERVER_LIMIT,
    RESUME_HISTORY_LENGTH,
    SavedConversation,
    ServerConnectionMode,
    ServerState,
    build_http_client,
    build_recent_server,
)
from a2a_handler.tui.server.views import ConnectionBar, ServerView

logger = get_logger(__name__)


class ServerTab(Container):
    """A single server tab with its own connection state."""

    class TitleChanged(TextualMessage):
        """Posted when the server tab title should change."""

        def __init__(self, server_id: str, title: str) -> None:
            super().__init__()
            self.server_id = server_id
            self.title = title

    def __init__(
        self,
        server_id: str,
        title: str,
        initial_bearer_token: str | None = None,
        auto_connect_server: str | None = None,
        auto_connect_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(id=server_id, **kwargs)
        self.server_id = server_id
        self.title = title
        self.state = ServerState()
        self.http_client: httpx.AsyncClient | None = None
        self._agent_service: A2AService | None = None
        self._server_catalog = ServerCatalog()
        self._servers_by_id: dict[str, ServerDefinition] = {}
        self._server_credentials: dict[str, AuthCredentials] = {}
        self._server_warnings: dict[str, str] = {}
        self._initial_bearer_token = initial_bearer_token
        self._auto_connect_server = auto_connect_server
        self._auto_connect_url = auto_connect_url
        self._syncing_auth_depth = 0
        self._suspend_connect_events = False
        self._log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield ServerView()

    @property
    def is_connected(self) -> bool:
        return self.state.mode == ServerConnectionMode.CONNECTED

    @property
    def current_agent_card(self) -> AgentCard | None:
        return self.state.agent_card

    @property
    def current_agent_url(self) -> str | None:
        return self.state.agent_url

    @contextlib.contextmanager
    def _suppressing_auth_events(self) -> Generator[None, None, None]:
        self._syncing_auth_depth += 1
        try:
            yield
        finally:
            self._syncing_auth_depth -= 1

    @property
    def _is_syncing_auth_panel(self) -> bool:
        return self._syncing_auth_depth > 0

    async def on_mount(self) -> None:
        self._suspend_connect_events = True
        server_view = self._get_server_view()
        self._load_server_catalog()

        if self._initial_bearer_token:
            with self._suppressing_auth_events():
                server_view.messages_panel().set_auth_credentials(
                    AuthCredentials(
                        auth_type=AuthType.BEARER,
                        value=self._initial_bearer_token,
                    )
                )

        self._show_disconnected_state()
        self._suspend_connect_events = False

        if self._auto_connect_server:
            self._select_server_by_name(self._auto_connect_server)
            await self.handle_connect_button()
        elif self._auto_connect_url:
            self._select_manual_url(self._auto_connect_url)
            await self.handle_connect_button()

    def _select_server_by_name(self, server_name: str) -> None:
        """Pre-select a named server in the picker."""
        connection_bar = self._get_connection_bar()
        for server_def in self._servers_by_id.values():
            if server_def.name == server_name:
                select = connection_bar.query_one("#server-select", Select)
                with connection_bar.prevent(Select.Changed):
                    select.value = server_def.server_id
                connection_bar._sync_manual_input()
                self._sync_auth_to_server(server_def.server_id)
                return
        logger.warning("Server '%s' not found in catalog", server_name)

    def _select_manual_url(self, url: str) -> None:
        """Pre-select manual URL entry and fill in the URL."""
        connection_bar = self._get_connection_bar()
        select = connection_bar.query_one("#server-select", Select)
        with connection_bar.prevent(Select.Changed):
            select.value = MANUAL_SERVER_ID
        connection_bar._sync_manual_input()
        connection_bar.query_one("#manual-agent-url", Input).value = url

    async def on_unmount(self) -> None:
        if self.http_client:
            await self.http_client.aclose()

    def _get_server_view(self) -> ServerView:
        return self.query_one(ServerView)

    def _get_connection_bar(self) -> ConnectionBar:
        return self._get_server_view().connection_bar()

    def _try_get_server_view(self) -> ServerView | None:
        try:
            return self.query_one(ServerView)
        except Exception:
            return None

    def load_logs(self, lines: list[str]) -> None:
        self._log_lines = list(lines)
        server_view = self._try_get_server_view()
        if server_view is not None:
            server_view.messages_panel().load_logs(self._log_lines)

    def add_log(self, line: str) -> None:
        self._log_lines.append(line)
        server_view = self._try_get_server_view()
        if server_view is not None:
            server_view.messages_panel().add_log(line)

    def _load_server_catalog(self) -> None:
        self._server_catalog = load_server_catalog()
        self._server_credentials = {}
        self._server_warnings = {}
        self._servers_by_id = {}

        configured_servers = (
            *self._server_catalog.repository_servers,
            *self._server_catalog.global_servers,
        )
        for server_def in configured_servers:
            self._servers_by_id[server_def.server_id] = server_def
            credentials, warning = resolve_server_credentials(server_def)
            if credentials:
                self._server_credentials[server_def.server_id] = credentials
            if warning:
                self._server_warnings[server_def.server_id] = warning
                logger.warning("Server %s: %s", server_def.label, warning)

        configured_urls = self._server_catalog.all_configured_urls()
        recent_servers: list[ServerDefinition] = []
        for agent_url in get_session_store().recent_agent_urls(RECENT_SERVER_LIMIT):
            if agent_url in configured_urls:
                continue
            recent_server = build_recent_server(agent_url)
            recent_servers.append(recent_server)
            self._servers_by_id[recent_server.server_id] = recent_server

        connection_bar = self._get_connection_bar()
        connection_bar.set_server_catalog(
            repository_servers=self._server_catalog.repository_servers,
            global_servers=self._server_catalog.global_servers,
            recent_servers=tuple(recent_servers),
        )

        selected = connection_bar.get_selected_server()
        if selected is not None:
            self._sync_auth_to_server(selected.server_id)

    def _sync_auth_to_server(self, server_id: str) -> None:
        """Sync the auth panel to show the selected server's credentials."""
        messages_panel = self._get_server_view().messages_panel()
        credentials = self._server_credentials.get(server_id)
        warning = self._server_warnings.get(server_id)

        with self._suppressing_auth_events():
            if credentials is not None:
                messages_panel.set_auth_credentials(credentials)
            else:
                messages_panel.set_auth_credentials(None)

        if warning:
            messages_panel.add_system_message(warning)

    def _show_disconnected_state(self) -> None:
        server_view = self._get_server_view()
        server_view.connection_bar().show_disconnected_badges()
        server_view.agent_card_panel().update_card(None)
        server_view.input_panel().set_enabled(False)

    def _build_connect_error_message(self, error: InputValidationError) -> str:
        if error.suggestion:
            return f"{error.message}. {error.suggestion}"
        return error.message

    async def _connect_to_agent(
        self,
        agent_url: str,
        credentials: AuthCredentials | None,
    ) -> AgentCard:
        previous_http_client = self.http_client
        previous_service = self._agent_service
        next_http_client = build_http_client(credentials=credentials)
        logger.info("Connecting server %s to %s", self.server_id, agent_url)
        next_service = A2AService(
            next_http_client,
            agent_url,
            credentials=credentials,
        )
        try:
            agent_card = await next_service.get_card()
        except Exception:
            await next_http_client.aclose()
            self.http_client = previous_http_client
            self._agent_service = previous_service
            raise

        if previous_http_client is not None:
            await previous_http_client.aclose()
        self.http_client = next_http_client
        self._agent_service = next_service
        return agent_card

    async def _apply_connected_ui(
        self,
        warning: str | None = None,
        resumed: bool = False,
        saved_conversation: SavedConversation | None = None,
    ) -> None:
        agent_card = self.state.agent_card
        assert agent_card is not None

        server_view = self._get_server_view()
        await server_view.reset_session()
        server_view.agent_card_panel().update_card(agent_card)

        if resumed and saved_conversation is not None:
            await self._hydrate_resumed_history(server_view, saved_conversation)

        if warning:
            server_view.messages_panel().add_system_message(warning)
        conversation_summary = (
            "resumed saved context" if resumed else "fresh server context"
        )
        server_view.messages_panel().add_system_message(
            f"Conversation: {conversation_summary}"
        )
        server_view.messages_panel().add_system_message(
            f"Connected to {agent_card.name}"
        )
        server_view.input_panel().set_enabled(True)
        server_view.input_panel().focus_input()
        self._refresh_status_badges()

    @on(Select.Changed, "#server-select")
    def _handle_server_select_changed(self) -> None:
        if self._suspend_connect_events:
            return
        connection_bar = self._get_connection_bar()
        connection_bar._sync_manual_input()

        selected = connection_bar.get_selected_server()
        if selected is not None:
            self._sync_auth_to_server(selected.server_id)
        else:
            with self._suppressing_auth_events():
                self._get_server_view().messages_panel().set_auth_credentials(None)

    @on(RadioSet.Changed, "#auth-type-selector")
    @on(
        Input.Changed,
        "#api-key-input, #api-key-header-input, #bearer-token-input, "
        "#custom-headers-input, #mtls-cert-input, #mtls-key-input, #mtls-ca-input, "
        "#oauth2-token-url-input, #oauth2-client-id-input, "
        "#oauth2-client-secret-input, #oauth2-scopes-input",
    )
    def _handle_auth_field_changed(self) -> None:
        if self._is_syncing_auth_panel:
            return
        if self.is_connected:
            self._refresh_status_badges()

    @on(Button.Pressed, "#connect-btn")
    async def handle_connect_button(self, force_fresh: bool = False) -> None:
        connection_bar = self._get_connection_bar()
        selected_server = connection_bar.get_selected_server()
        agent_url = connection_bar.get_url()

        messages_panel = self._get_server_view().messages_panel()

        if not agent_url:
            if connection_bar._is_manual_selected():
                messages_panel.add_system_message("Please enter an agent URL")
            else:
                messages_panel.add_system_message("Choose a server or switch to Manual")
            return

        try:
            validate_agent_url(agent_url)
        except InputValidationError as error:
            messages_panel.add_system_message(self._build_connect_error_message(error))
            return

        connection_bar.set_status(f"Connecting to {agent_url}...")

        try:
            credentials = messages_panel.get_auth_credentials()

            if credentials is None and selected_server is not None:
                auth_source = (
                    f"{selected_server.origin_label.lower()} server "
                    f"'{selected_server.label}' (no default auth)"
                )
            elif selected_server is not None:
                auth_source = (
                    f"{selected_server.origin_label.lower()} server "
                    f"'{selected_server.label}' default"
                )
            else:
                auth_source = "manual override" if credentials is not None else "none"

            agent_card = await self._connect_to_agent(agent_url, credentials)

            session = get_session_store().find(agent_url)
            saved_conversation, session_warning = resolve_saved_conversation(
                session, agent_url
            )

            resumed = (
                not force_fresh
                and saved_conversation is not None
                and session_warning is None
            )
            context_id = str(uuid.uuid4())
            resumed_task_id: str | None = None
            if resumed:
                assert saved_conversation is not None
                context_id = saved_conversation.context_id
                resumed_task_id = saved_conversation.task_id

            self.state.agent_card = agent_card
            self.state.agent_url = agent_url
            self.state.current_context_id = context_id
            self.state.current_task_id = resumed_task_id
            self.state.auth_source = auth_source
            self.state.connected_server_def = selected_server
            self.state.mode = ServerConnectionMode.CONNECTED
            self._persist_session_state()

            combined_warning = None
            if session_warning:
                combined_warning = session_warning

            await self._apply_connected_ui(
                combined_warning,
                resumed=resumed,
                saved_conversation=saved_conversation,
            )
            self.post_message(self.TitleChanged(self.server_id, agent_card.name))

        except Exception as error:
            logger.error(
                "Connection failed for %s: %s",
                self.server_id,
                error,
                exc_info=True,
            )
            messages_panel.add_system_message(f"Connection failed: {error!s}")
            self.state.agent_card = None
            self.state.agent_url = None
            self._refresh_status_badges()

    @on(Input.Submitted, "#message-input")
    def handle_message_submit(self) -> None:
        if self.is_connected:
            self._send_message()

    @on(Button.Pressed, "#send-btn")
    def handle_send_button(self) -> None:
        if self.is_connected:
            self._send_message()

    @work(exclusive=True)
    async def _send_message(self) -> None:
        server_view = self._try_get_server_view()
        if (
            not self.is_connected
            or self.state.agent_url is None
            or self._agent_service is None
            or server_view is None
        ):
            return

        input_panel = server_view.input_panel()
        message_text = input_panel.get_message()
        if not message_text:
            return

        messages_panel = server_view.messages_panel()
        messages_panel.add_message("user", message_text)

        try:
            credentials = messages_panel.get_auth_credentials()
            if credentials is not None:
                self._agent_service.set_credentials(credentials)
            else:
                self._agent_service.clear_credentials()

            self._refresh_status_badges()

            response = await self._agent_service.send(
                message_text,
                context_id=self.state.current_context_id,
                task_id=self.state.current_task_id,
            )

            ctx_id = response_context_id(response)
            if ctx_id:
                self.state.current_context_id = ctx_id
            self.state.current_task_id = response_task_id(response)
            self._persist_session_state()

            messages_panel.add_agent_message(response)

            if isinstance(response, Task):
                messages_panel.update_task(response)
                if response.artifacts:
                    for artifact in response.artifacts:
                        messages_panel.update_artifact(
                            artifact,
                            response_task_id(response) or "",
                            self.state.current_context_id or "",
                        )

            self._refresh_status_badges()

        except Exception as error:
            logger.error(
                "Error sending message from %s: %s",
                self.server_id,
                error,
                exc_info=True,
            )
            messages_panel.add_system_message(f"Error: {error!s}")

    def _refresh_status_badges(self) -> None:
        server_view = self._try_get_server_view()
        if server_view is None:
            return

        if self.state.agent_url is None or self.state.agent_card is None:
            self._show_disconnected_state()
            return

        server_view.connection_bar().set_connected_status(
            agent_name=self.state.agent_card.name,
            auth_source=self.state.auth_source,
            protocol_version=self.state.agent_card.protocol_version,
            agent_version=self.state.agent_card.version,
        )

    def _persist_session_state(self) -> None:
        if self.state.agent_url is None:
            return
        get_session_store().set_conversation(
            self.state.agent_url,
            self.state.current_context_id,
            self.state.current_task_id,
        )

    def _load_task_into_live_view(self, server_view: ServerView, task: Task) -> None:
        messages_panel = server_view.messages_panel()
        seen_message_ids: set[str] = set()

        if task.history:
            for message in task.history:
                if message.message_id in seen_message_ids:
                    logger.debug(
                        "Skipping duplicate history message %s in resumed task %s",
                        message.message_id,
                        task.id,
                    )
                    continue
                seen_message_ids.add(message.message_id)
                self._load_history_message(messages_panel, message)

        messages_panel.update_task(task)
        if task.artifacts:
            for artifact in task.artifacts:
                messages_panel.update_artifact(
                    artifact,
                    task.id,
                    task.context_id,
                )

    def _load_history_message(
        self,
        messages_panel: TabbedMessagesPanel,
        message: A2AMessage,
    ) -> None:
        if not message.parts:
            return

        text = extract_text_from_message_parts(message.parts)
        if not text:
            return

        if message.role == Role.agent:
            messages_panel.add_agent_message(message)
            return

        if message.role == Role.user:
            messages_panel.add_message("user", text)
            return

        messages_panel.add_message("system", text)

    async def _hydrate_resumed_history(
        self,
        server_view: ServerView,
        saved_conversation: SavedConversation,
    ) -> None:
        if saved_conversation.task_id is None:
            return

        if self._agent_service is None:
            return

        try:
            task = await self._agent_service.get_task(
                saved_conversation.task_id,
                history_length=RESUME_HISTORY_LENGTH,
            )
        except Exception as error:
            logger.warning(
                "Failed to load resumed task history for %s (%s): %s",
                self.server_id,
                saved_conversation.task_id,
                error,
                exc_info=True,
            )
            server_view.messages_panel().add_system_message(
                "Resumed saved context, but prior messages could not be loaded."
            )
            return

        self._load_task_into_live_view(server_view, task)
