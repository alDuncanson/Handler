"""Per-remote workspace controller."""

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
    validate_resource_id,
)
from a2a_handler.connections import (
    ConnectionCatalog,
    ConnectionDefinition,
    ConnectionSource,
    connection_source_label,
    load_connection_catalog,
    resolve_connection_credentials,
)
from a2a_handler.service import A2AService, SendResult, extract_text_from_message_parts
from a2a_handler.session import get_session_store
from a2a_handler.tui.components import TabbedMessagesPanel
from a2a_handler.tui.workspace_types import (
    RECENT_CONNECTION_LIMIT,
    RESUME_HISTORY_LENGTH,
    SavedConversation,
    WorkspaceAuthMode,
    WorkspaceConnectionMode,
    WorkspaceLaunchMode,
    WorkspaceState,
    build_http_client,
    build_recent_connection,
)
from a2a_handler.tui.workspace_views import RemoteConnectView, RemoteLiveView

logger = get_logger(__name__)


class RemoteWorkspace(Container):
    """A single remote workspace tab with its own connection state."""

    class TitleChanged(TextualMessage):
        """Posted when the workspace tab title should change."""

        def __init__(self, workspace_id: str, title: str) -> None:
            super().__init__()
            self.workspace_id = workspace_id
            self.title = title

    def __init__(
        self,
        workspace_id: str,
        title: str,
        initial_bearer_token: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(id=workspace_id, **kwargs)
        self.workspace_id = workspace_id
        self.title = title
        self.state = WorkspaceState()
        self.http_client: httpx.AsyncClient | None = None
        self._agent_service: A2AService | None = None
        self._connection_catalog = ConnectionCatalog()
        self._connections_by_id: dict[str, ConnectionDefinition] = {}
        self._connection_credentials: dict[str, AuthCredentials] = {}
        self._connection_warnings: dict[str, str] = {}
        self._initial_bearer_token = initial_bearer_token
        self._syncing_auth_depth = 0
        self._suspend_connect_events = False
        self._log_lines: list[str] = []

    @property
    def current_agent_card(self) -> AgentCard | None:
        return self.state.agent_card

    @current_agent_card.setter
    def current_agent_card(self, value: AgentCard | None) -> None:
        self.state.agent_card = value

    @property
    def current_agent_url(self) -> str | None:
        return self.state.agent_url

    @current_agent_url.setter
    def current_agent_url(self, value: str | None) -> None:
        self.state.agent_url = value

    @property
    def current_context_id(self) -> str | None:
        return self.state.current_context_id

    @current_context_id.setter
    def current_context_id(self, value: str | None) -> None:
        self.state.current_context_id = value

    @property
    def current_task_id(self) -> str | None:
        return self.state.current_task_id

    @current_task_id.setter
    def current_task_id(self, value: str | None) -> None:
        self.state.current_task_id = value

    def compose(self) -> ComposeResult:
        yield RemoteLiveView(self.title)

    @property
    def is_connected(self) -> bool:
        return self.state.mode == WorkspaceConnectionMode.CONNECTED

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
        live_view = self._get_live_view()
        self._load_connection_catalog()
        connect_view = self._get_connect_view()
        connect_view.set_auth_mode(WorkspaceAuthMode.USE_CONNECTION_DEFAULT)
        self.state.auth_mode = connect_view.get_auth_mode()

        if self._initial_bearer_token:
            connect_view.set_auth_mode(WorkspaceAuthMode.OVERRIDE)
            with self._suppressing_auth_events():
                live_view.messages_panel().set_auth_credentials(
                    AuthCredentials(
                        auth_type=AuthType.BEARER,
                        value=self._initial_bearer_token,
                    )
                )
            self.state.auth_mode = WorkspaceAuthMode.OVERRIDE

        live_view.show_disconnected_state()
        self._refresh_connect_selection()
        self._suspend_connect_events = False

    async def on_unmount(self) -> None:
        if self.http_client:
            await self.http_client.aclose()

    def _get_live_view(self) -> RemoteLiveView:
        return self.query_one(RemoteLiveView)

    def _get_connect_view(self) -> RemoteConnectView:
        return self._get_live_view().connect_view()

    def _try_get_live_view(self) -> RemoteLiveView | None:
        try:
            return self.query_one(RemoteLiveView)
        except Exception:
            return None

    def load_logs(self, lines: list[str]) -> None:
        self._log_lines = list(lines)
        live_view = self._try_get_live_view()
        if live_view is not None:
            live_view.messages_panel().load_logs(self._log_lines)

    def add_log(self, line: str) -> None:
        self._log_lines.append(line)
        live_view = self._try_get_live_view()
        if live_view is not None:
            live_view.messages_panel().add_log(line)

    def _load_connection_catalog(self) -> None:
        self._connection_catalog = load_connection_catalog()
        self._connection_credentials = {}
        self._connection_warnings = {}
        self._connections_by_id = {}

        configured_connections = (
            *self._connection_catalog.repository_connections,
            *self._connection_catalog.global_connections,
        )
        for connection_def in configured_connections:
            self._connections_by_id[connection_def.connection_id] = connection_def
            credentials, warning = resolve_connection_credentials(connection_def)
            if credentials:
                self._connection_credentials[connection_def.connection_id] = credentials
            if warning:
                self._connection_warnings[connection_def.connection_id] = warning
                logger.warning("Connection %s: %s", connection_def.label, warning)

        configured_urls = self._connection_catalog.all_configured_urls()
        recent_connections: list[ConnectionDefinition] = []
        for agent_url in get_session_store().recent_agent_urls(RECENT_CONNECTION_LIMIT):
            if agent_url in configured_urls:
                continue
            recent_connection = build_recent_connection(agent_url)
            recent_connections.append(recent_connection)
            self._connections_by_id[recent_connection.connection_id] = recent_connection

        self._get_connect_view().set_connection_catalog(
            repository_connections=self._connection_catalog.repository_connections,
            global_connections=self._connection_catalog.global_connections,
            recent_connections=tuple(recent_connections),
        )

    def _refresh_connect_selection(self) -> None:
        self._refresh_connect_selection_summary()
        self._refresh_connect_saved_conversation()
        self._refresh_connect_auth_source_status()

    def _refresh_connect_selection_summary(self) -> None:
        connect_view = self._get_connect_view()
        active_source = connect_view.get_active_source()
        selected_connection = connect_view.get_selected_connection()
        agent_url = connect_view.get_url()
        source_label = connection_source_label(active_source)

        if selected_connection is not None:
            summary = f"{source_label} · {selected_connection.label}"
        elif active_source == ConnectionSource.MANUAL:
            if agent_url:
                summary = "Manual URL"
            else:
                summary = "Manual URL · URL not set"
        else:
            summary = f"{source_label} · unavailable"

        connect_view.set_selected_connection_summary(summary)

    def _build_connection_summary(
        self,
        selected_connection: ConnectionDefinition | None,
        active_source: ConnectionSource,
        agent_url: str,
    ) -> str:
        if selected_connection is not None:
            return f"{selected_connection.origin_label} · {selected_connection.label}"
        if active_source == ConnectionSource.MANUAL:
            return f"Manual URL · {agent_url}"
        return connection_source_label(active_source)

    def _resolve_connection_credentials(
        self,
        selected_connection: ConnectionDefinition | None,
        active_source: ConnectionSource,
        auth_mode: WorkspaceAuthMode,
        override_credentials: AuthCredentials | None,
    ) -> tuple[AuthCredentials | None, str, str | None]:
        """Resolve connect-time credentials from explicit source selection."""
        if auth_mode == WorkspaceAuthMode.OVERRIDE:
            if override_credentials is not None:
                return override_credentials, "manual override", None
            return None, "manual override (none)", None

        if selected_connection is None:
            if active_source == ConnectionSource.MANUAL:
                return None, "manual URL (no default auth)", None
            return (
                None,
                f"{connection_source_label(active_source)} connection unavailable",
                None,
            )

        credentials = self._connection_credentials.get(
            selected_connection.connection_id
        )
        if credentials is not None:
            return (
                credentials,
                (
                    f"{selected_connection.origin_label.lower()} connection "
                    f"'{selected_connection.label}' default"
                ),
                None,
            )

        warning = self._connection_warnings.get(selected_connection.connection_id)
        if warning:
            return (
                None,
                (
                    f"{selected_connection.origin_label.lower()} connection "
                    f"'{selected_connection.label}' default unavailable"
                ),
                warning,
            )

        return (
            None,
            (
                f"{selected_connection.origin_label.lower()} connection "
                f"'{selected_connection.label}' (no default auth)"
            ),
            None,
        )

    def _resolve_saved_conversation(
        self,
        agent_url: str,
    ) -> tuple[SavedConversation | None, str | None]:
        session = get_session_store().find(agent_url)
        if session is None or not session.context_id:
            return None, None

        try:
            validate_resource_id(session.context_id, "context_id")
        except InputValidationError as error:
            logger.warning(
                "Ignoring saved context for %s: %s", agent_url, error.message
            )
            return (
                None,
                f"saved session ignored: {self._build_connect_error_message(error)}",
            )

        task_id = session.task_id
        if task_id:
            try:
                validate_resource_id(task_id, "task_id")
            except InputValidationError as error:
                logger.warning(
                    "Ignoring saved task ID for %s: %s", agent_url, error.message
                )
                task_id = None

        return SavedConversation(context_id=session.context_id, task_id=task_id), None

    def _refresh_connect_saved_conversation(self) -> None:
        connect_view = self._get_connect_view()
        agent_url = connect_view.get_url()
        if not agent_url:
            self.state.saved_conversation = None
            self.state.launch_mode = WorkspaceLaunchMode.START_FRESH
            connect_view.set_saved_conversation(None)
            return

        saved_conversation, warning = self._resolve_saved_conversation(agent_url)
        self.state.saved_conversation = saved_conversation
        connect_view.set_saved_conversation(saved_conversation, warning=warning)
        self.state.launch_mode = connect_view.get_launch_mode()

    def _refresh_connect_auth_source_status(self) -> None:
        connect_view = self._get_connect_view()
        agent_url = connect_view.get_url()
        if not agent_url:
            connect_view.set_auth_source_status("none")
            return

        auth_mode = connect_view.get_auth_mode()
        override_credentials = (
            connect_view.get_auth_credentials()
            if auth_mode == WorkspaceAuthMode.OVERRIDE
            else None
        )
        _, source_description, warning = self._resolve_connection_credentials(
            selected_connection=connect_view.get_selected_connection(),
            active_source=connect_view.get_active_source(),
            auth_mode=auth_mode,
            override_credentials=override_credentials,
        )
        connect_view.set_auth_source_status(
            source_description,
            tone="warning" if warning else None,
        )

    def _refresh_live_summary(self) -> None:
        live_view = self._try_get_live_view()
        if live_view is None:
            return

        if self.current_agent_url is None or self.current_agent_card is None:
            live_view.show_disconnected_state()
            return

        live_view.connect_view().set_connected_status(
            agent_name=self.current_agent_card.name,
            context_id=self.current_context_id,
        )

    def _conversation_summary(self) -> str:
        if self.state.launch_mode == WorkspaceLaunchMode.RESUME_SESSION:
            return "resumed saved context"
        return "fresh workspace context"

    def _persist_session_state(self) -> None:
        if self.current_agent_url is None:
            return
        get_session_store().set_conversation(
            self.current_agent_url,
            self.current_context_id,
            self.current_task_id,
        )

    def _load_task_into_live_view(self, live_view: RemoteLiveView, task: Task) -> None:
        messages_panel = live_view.messages_panel()
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
            messages_panel.add_agent_message(SendResult(message=message, text=text))
            return

        if message.role == Role.user:
            messages_panel.add_message("user", text)
            return

        messages_panel.add_message("system", text)

    async def _hydrate_resumed_history(self, live_view: RemoteLiveView) -> None:
        if self.state.launch_mode != WorkspaceLaunchMode.RESUME_SESSION:
            return

        saved_conversation = self.state.saved_conversation
        if saved_conversation is None or saved_conversation.task_id is None:
            return

        if self._agent_service is None:
            return

        try:
            task_result = await self._agent_service.get_task(
                saved_conversation.task_id,
                history_length=RESUME_HISTORY_LENGTH,
            )
        except Exception as error:
            logger.warning(
                "Failed to load resumed task history for %s (%s): %s",
                self.workspace_id,
                saved_conversation.task_id,
                error,
                exc_info=True,
            )
            live_view.messages_panel().add_system_message(
                "Resumed saved context, but prior messages could not be loaded."
            )
            return

        self._load_task_into_live_view(live_view, task_result.task)

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
        logger.info("Connecting workspace %s to %s", self.workspace_id, agent_url)
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

    async def _show_live_view(self, warning: str | None = None) -> None:
        agent_card = self.current_agent_card
        assert agent_card is not None

        live_view = self._get_live_view()
        await live_view.prepare_for_connection()
        live_view.agent_card_panel().update_card(agent_card)
        with self._suppressing_auth_events():
            if self.state.auth_mode == WorkspaceAuthMode.OVERRIDE:
                live_view.messages_panel().set_auth_credentials(
                    self.state.connected_credentials
                )

        await self._hydrate_resumed_history(live_view)

        if warning:
            live_view.messages_panel().add_system_message(warning)
        live_view.messages_panel().add_system_message(
            f"Conversation: {self._conversation_summary()}"
        )
        live_view.messages_panel().add_system_message(f"Connected to {agent_card.name}")
        live_view.input_panel().set_enabled(True)
        live_view.input_panel().focus_input()
        self._refresh_live_summary()

    @on(Select.Changed, "#connection-source-select")
    def _handle_connection_source_changed(self) -> None:
        if self._suspend_connect_events:
            return
        self._get_connect_view().sync_source_controls()
        self._refresh_connect_selection()

    @on(Select.Changed, "#connection-target-select")
    def _handle_connection_selection_changed(self) -> None:
        if self._suspend_connect_events:
            return
        self._refresh_connect_selection()

    @on(Input.Changed, "#manual-agent-url")
    def _handle_manual_url_changed(self) -> None:
        if self._suspend_connect_events:
            return
        self._refresh_connect_selection()

    @on(Select.Changed, "#launch-mode-select")
    def _handle_launch_mode_changed(self) -> None:
        if self._suspend_connect_events:
            return
        self.state.launch_mode = self._get_connect_view().get_launch_mode()

    @on(Select.Changed, "#auth-mode-select")
    def _handle_connect_auth_mode_changed(self) -> None:
        if self._suspend_connect_events:
            return
        connect_view = self._get_connect_view()
        self.state.auth_mode = connect_view.get_auth_mode()
        self._refresh_connect_auth_source_status()
        if self.is_connected:
            self._refresh_live_summary()

    @on(RadioSet.Changed, "#auth-type-selector")
    @on(
        Input.Changed,
        "#api-key-input, #api-key-header-input, #bearer-token-input, "
        "#custom-headers-input, #mtls-cert-input, #mtls-key-input, #mtls-ca-input",
    )
    def _handle_auth_field_changed(self) -> None:
        if self._is_syncing_auth_panel:
            return

        connect_view = self._get_connect_view()
        if connect_view.get_auth_mode() != WorkspaceAuthMode.OVERRIDE:
            connect_view.set_auth_mode(WorkspaceAuthMode.OVERRIDE)
        if self.is_connected:
            self.state.auth_mode = WorkspaceAuthMode.OVERRIDE
            self._refresh_connect_auth_source_status()
            self._refresh_live_summary()
            return

        self.state.auth_mode = WorkspaceAuthMode.OVERRIDE
        self._refresh_connect_auth_source_status()

    @on(Button.Pressed, "#connect-btn")
    async def handle_connect_button(self) -> None:
        connect_view = self._get_connect_view()
        active_source = connect_view.get_active_source()
        selected_connection = connect_view.get_selected_connection()
        agent_url = connect_view.get_url()

        if not agent_url:
            if active_source == ConnectionSource.MANUAL:
                connect_view.set_status("Please enter an agent URL", tone="warning")
            else:
                connect_view.set_status(
                    "Choose a connection or switch to Manual", tone="warning"
                )
            return

        try:
            validate_agent_url(agent_url)
        except InputValidationError as error:
            connect_view.set_status(
                self._build_connect_error_message(error),
                tone="error",
            )
            return

        connect_view.set_status(f"Connecting to {agent_url}...")

        try:
            auth_mode = connect_view.get_auth_mode()
            override_credentials = (
                connect_view.get_auth_credentials()
                if auth_mode == WorkspaceAuthMode.OVERRIDE
                else None
            )
            credentials, source_description, warning = (
                self._resolve_connection_credentials(
                    selected_connection=selected_connection,
                    active_source=active_source,
                    auth_mode=auth_mode,
                    override_credentials=override_credentials,
                )
            )
            connect_view.set_auth_source_status(
                source_description,
                tone="warning" if warning else None,
            )

            agent_card = await self._connect_to_agent(agent_url, credentials)

            saved_conversation = self.state.saved_conversation
            launch_mode = connect_view.get_launch_mode()
            context_id = str(uuid.uuid4())
            if (
                launch_mode == WorkspaceLaunchMode.RESUME_SESSION
                and saved_conversation is not None
            ):
                context_id = saved_conversation.context_id

            self.current_agent_card = agent_card
            self.current_agent_url = agent_url
            self.current_context_id = context_id
            self.current_task_id = (
                saved_conversation.task_id
                if launch_mode == WorkspaceLaunchMode.RESUME_SESSION
                and saved_conversation is not None
                else None
            )
            self.state.connected_credentials = credentials
            self.state.auth_source = source_description
            self.state.auth_mode = auth_mode
            self.state.launch_mode = launch_mode
            self.state.mode = WorkspaceConnectionMode.CONNECTED
            self.state.connection_summary = self._build_connection_summary(
                selected_connection=selected_connection,
                active_source=active_source,
                agent_url=agent_url,
            )
            self._persist_session_state()

            await self._show_live_view(warning)
            self.post_message(self.TitleChanged(self.workspace_id, agent_card.name))

        except Exception as error:
            logger.error(
                "Connection failed for %s: %s", self.workspace_id, error, exc_info=True
            )
            connect_view.set_status(f"Connection failed: {error!s}", tone="error")

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
        live_view = self._try_get_live_view()
        if (
            not self.is_connected
            or self.current_agent_url is None
            or self._agent_service is None
            or live_view is None
        ):
            return

        input_panel = live_view.input_panel()
        message_text = input_panel.get_message()
        if not message_text:
            return

        messages_panel = live_view.messages_panel()
        messages_panel.add_message("user", message_text)

        try:
            if self.state.auth_mode == WorkspaceAuthMode.OVERRIDE:
                credentials = messages_panel.get_auth_credentials()
                if credentials is not None:
                    self._agent_service.set_credentials(credentials)
                else:
                    self._agent_service.clear_credentials()
            elif self.state.connected_credentials is not None:
                self._agent_service.set_credentials(self.state.connected_credentials)
            else:
                self._agent_service.clear_credentials()

            self._refresh_live_summary()

            send_result = await self._agent_service.send(
                message_text,
                context_id=self.current_context_id,
            )

            if send_result.context_id:
                self.current_context_id = send_result.context_id
            self.current_task_id = send_result.task_id
            self._persist_session_state()

            messages_panel.add_agent_message(send_result)

            if send_result.task:
                messages_panel.update_task(send_result.task)
                if send_result.task.artifacts:
                    for artifact in send_result.task.artifacts:
                        messages_panel.update_artifact(
                            artifact,
                            send_result.task_id or "",
                            self.current_context_id or "",
                        )

            self._refresh_live_summary()

        except Exception as error:
            logger.error(
                "Error sending message from %s: %s",
                self.workspace_id,
                error,
                exc_info=True,
            )
            messages_panel.add_system_message(f"Error: {error!s}")
