"""Workspace shell and per-remote workspace state for the TUI."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx
from a2a.types import AgentCard, Message as A2AMessage, Role, Task
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message as TextualMessage
from textual.widgets import (
    Button,
    ContentSwitcher,
    Input,
    RadioButton,
    RadioSet,
    Select,
    Static,
    Tab,
    TabbedContent,
    TabPane,
    Tabs,
)

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
from a2a_handler.service import (
    A2AService,
    SendResult,
    extract_text_from_message_parts,
)
from a2a_handler.session import get_session_store
from a2a_handler.tui.components import (
    AgentCardPanel,
    AuthPanel,
    InputPanel,
    TabbedMessagesPanel,
)

logger = get_logger(__name__)

DEFAULT_HTTP_TIMEOUT_SECONDS = 120
SHORT_ID_LENGTH = 12
RESUME_HISTORY_LENGTH = 100
RECENT_CONNECTION_LIMIT = 12
EMPTY_CONNECTION_ID = "__empty__"

CONFIGURED_CONNECTION_SOURCES = (
    ConnectionSource.REPOSITORY,
    ConnectionSource.GLOBAL,
    ConnectionSource.RECENT,
)
CONNECTION_SOURCE_ORDER = (*CONFIGURED_CONNECTION_SOURCES, ConnectionSource.MANUAL)
SOURCE_TAB_IDS = {
    ConnectionSource.REPOSITORY: "source-repository",
    ConnectionSource.GLOBAL: "source-global",
    ConnectionSource.RECENT: "source-recent",
    ConnectionSource.MANUAL: "source-manual",
}
SOURCE_SELECT_IDS = {
    ConnectionSource.REPOSITORY: "repository-connections",
    ConnectionSource.GLOBAL: "global-connections",
    ConnectionSource.RECENT: "recent-connections",
}
EMPTY_SOURCE_LABELS = {
    ConnectionSource.REPOSITORY: "No repository connections configured",
    ConnectionSource.GLOBAL: "No global connections configured",
    ConnectionSource.RECENT: "No recent connections yet",
}
SOURCE_HINTS = {
    ConnectionSource.REPOSITORY: "Repository-defined connections from this checkout.",
    ConnectionSource.GLOBAL: "Global connections available across repositories.",
    ConnectionSource.RECENT: "Recently used agent URLs from prior sessions.",
    ConnectionSource.MANUAL: "Connect to any agent URL manually.",
}


class WorkspaceConnectionMode(str, Enum):
    """High-level lifecycle mode for a remote workspace."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"


class WorkspaceLaunchMode(str, Enum):
    """How a workspace should initialize its conversation state."""

    START_FRESH = "start_fresh"
    RESUME_SESSION = "resume_session"


class WorkspaceAuthMode(str, Enum):
    """How connect-time auth should be chosen for a workspace."""

    USE_CONNECTION_DEFAULT = "use_connection_default"
    OVERRIDE = "override"


@dataclass(frozen=True, slots=True)
class SavedConversation:
    """Resume metadata loaded from a saved agent session."""

    context_id: str
    task_id: str | None = None


@dataclass(slots=True)
class WorkspaceState:
    """Explicit per-workspace runtime state."""

    mode: WorkspaceConnectionMode = WorkspaceConnectionMode.DISCONNECTED
    agent_card: AgentCard | None = None
    agent_url: str | None = None
    current_context_id: str | None = None
    current_task_id: str | None = None
    connected_credentials: AuthCredentials | None = None
    auth_source: str = "none"
    auth_mode: WorkspaceAuthMode = WorkspaceAuthMode.USE_CONNECTION_DEFAULT
    launch_mode: WorkspaceLaunchMode = WorkspaceLaunchMode.START_FRESH
    saved_conversation: SavedConversation | None = None
    connection_summary: str = "Manual URL"


def summarize_identifier(value: str) -> str:
    """Shorten long IDs for compact UI summaries."""
    if len(value) <= SHORT_ID_LENGTH:
        return value
    return f"{value[:SHORT_ID_LENGTH]}..."


def build_http_client(
    timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
    credentials: AuthCredentials | None = None,
) -> httpx.AsyncClient:
    """Build an HTTP client with the specified timeout."""
    if credentials and credentials.auth_type == AuthType.MTLS:
        return httpx.AsyncClient(
            timeout=timeout_seconds,
            verify=credentials.build_ssl_context(),
        )
    return httpx.AsyncClient(timeout=timeout_seconds)


def build_recent_connection(agent_url: str) -> ConnectionDefinition:
    """Create a runtime-only connection option for recent usage."""
    return ConnectionDefinition(
        connection_id=f"recent:{agent_url}",
        source=ConnectionSource.RECENT,
        name=None,
        agent_url=agent_url,
        origin_label=connection_source_label(ConnectionSource.RECENT),
    )


class RemoteConnectView(Container):
    """Centered pre-connect view for a remote workspace."""

    def __init__(self, workspace_title: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._workspace_title = workspace_title
        self._connections_by_id: dict[str, ConnectionDefinition] = {}

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="connect-scroll"):
            with Container(id="connect-stage"):
                with Container(classes="connect-canvas"):
                    with Vertical(id="connect-card"):
                        yield Static("Remote Workspace", classes="connect-eyebrow")
                        yield Static(self._workspace_title, id="connect-title")
                        yield Static(
                            "Pick a connection source, review the defaults, and open a workspace.",
                            id="connect-subtitle",
                        )
                        with Vertical(id="connect-form"):
                            with TabbedContent(
                                initial=SOURCE_TAB_IDS[ConnectionSource.REPOSITORY],
                                id="connection-source-content",
                            ):
                                with TabPane(
                                    "Repository",
                                    id=SOURCE_TAB_IDS[ConnectionSource.REPOSITORY],
                                    classes="connection-source-pane",
                                ):
                                    yield Static(
                                        SOURCE_HINTS[ConnectionSource.REPOSITORY],
                                        classes="connection-source-hint",
                                    )
                                    yield Select(
                                        [
                                            (
                                                EMPTY_SOURCE_LABELS[
                                                    ConnectionSource.REPOSITORY
                                                ],
                                                EMPTY_CONNECTION_ID,
                                            )
                                        ],
                                        allow_blank=False,
                                        value=EMPTY_CONNECTION_ID,
                                        id=SOURCE_SELECT_IDS[
                                            ConnectionSource.REPOSITORY
                                        ],
                                    )
                                with TabPane(
                                    "Global",
                                    id=SOURCE_TAB_IDS[ConnectionSource.GLOBAL],
                                    classes="connection-source-pane",
                                ):
                                    yield Static(
                                        SOURCE_HINTS[ConnectionSource.GLOBAL],
                                        classes="connection-source-hint",
                                    )
                                    yield Select(
                                        [
                                            (
                                                EMPTY_SOURCE_LABELS[
                                                    ConnectionSource.GLOBAL
                                                ],
                                                EMPTY_CONNECTION_ID,
                                            )
                                        ],
                                        allow_blank=False,
                                        value=EMPTY_CONNECTION_ID,
                                        id=SOURCE_SELECT_IDS[ConnectionSource.GLOBAL],
                                    )
                                with TabPane(
                                    "Recent",
                                    id=SOURCE_TAB_IDS[ConnectionSource.RECENT],
                                    classes="connection-source-pane",
                                ):
                                    yield Static(
                                        SOURCE_HINTS[ConnectionSource.RECENT],
                                        classes="connection-source-hint",
                                    )
                                    yield Select(
                                        [
                                            (
                                                EMPTY_SOURCE_LABELS[
                                                    ConnectionSource.RECENT
                                                ],
                                                EMPTY_CONNECTION_ID,
                                            )
                                        ],
                                        allow_blank=False,
                                        value=EMPTY_CONNECTION_ID,
                                        id=SOURCE_SELECT_IDS[ConnectionSource.RECENT],
                                    )
                                with TabPane(
                                    "Manual",
                                    id=SOURCE_TAB_IDS[ConnectionSource.MANUAL],
                                    classes="connection-source-pane",
                                ):
                                    yield Static(
                                        SOURCE_HINTS[ConnectionSource.MANUAL],
                                        classes="connection-source-hint",
                                    )
                                    yield Input(
                                        placeholder="http://localhost:8000",
                                        value="http://localhost:8000",
                                        id="manual-agent-url",
                                    )
                            yield Static(
                                "Connection: repository",
                                id="connection-selection-status",
                            )
                            yield Static(
                                "Conversation: start fresh",
                                id="conversation-status",
                            )
                            with Vertical(
                                id="launch-mode-container",
                                classes="launch-mode hidden",
                            ):
                                yield Static(
                                    "Choose how this workspace should open the conversation.",
                                    id="launch-mode-subtitle",
                                )
                                with RadioSet(id="launch-mode-selector"):
                                    yield RadioButton(
                                        "Resume saved session",
                                        id="launch-mode-resume",
                                    )
                                    yield RadioButton(
                                        "Start fresh",
                                        id="launch-mode-fresh",
                                        value=True,
                                    )
                            with Vertical(id="auth-mode-container"):
                                yield Static(
                                    "Authentication",
                                    id="auth-mode-subtitle",
                                )
                                with RadioSet(id="auth-mode-selector"):
                                    yield RadioButton(
                                        "Use connection default",
                                        id="auth-mode-default",
                                        value=True,
                                    )
                                    yield RadioButton(
                                        "Override for this workspace",
                                        id="auth-mode-override",
                                    )
                            yield Static("Auth source: none", id="auth-source-status")
                            yield AuthPanel(id="auth-panel", classes="hidden")
                            with Horizontal(id="connect-actions"):
                                yield Static("", id="connect-status")
                                yield Button("CONNECT", id="connect-btn")

    def on_mount(self) -> None:
        for widget in self.query(
            "#connection-source-content Tabs, #connection-source-content Tab, #connection-source-content TabPane"
        ):
            widget.can_focus = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Press connect when any connect-form input is submitted."""
        connect_button = self.query_one("#connect-btn", Button)
        self.post_message(Button.Pressed(connect_button))

    def activate_source(self, source: ConnectionSource) -> None:
        """Activate a connection source tab for tests and programmatic flows."""
        self.query_one(
            "#connection-source-content", TabbedContent
        ).active = SOURCE_TAB_IDS[source]

    def get_active_source(self) -> ConnectionSource:
        """Return the currently active connection source tab."""
        active_tab = (
            self.query_one("#connection-source-content", TabbedContent).active
            or SOURCE_TAB_IDS[ConnectionSource.REPOSITORY]
        )
        for source, tab_id in SOURCE_TAB_IDS.items():
            if tab_id == active_tab:
                return source
        return ConnectionSource.REPOSITORY

    def set_connection_catalog(
        self,
        repository_connections: tuple[ConnectionDefinition, ...],
        global_connections: tuple[ConnectionDefinition, ...],
        recent_connections: tuple[ConnectionDefinition, ...],
    ) -> None:
        """Populate source tabs with explicit connection options."""
        self._connections_by_id = {
            connection.connection_id: connection
            for connection in (
                *repository_connections,
                *global_connections,
                *recent_connections,
            )
        }
        self._set_source_options(ConnectionSource.REPOSITORY, repository_connections)
        self._set_source_options(ConnectionSource.GLOBAL, global_connections)
        self._set_source_options(ConnectionSource.RECENT, recent_connections)

    def _set_source_options(
        self,
        source: ConnectionSource,
        connections: tuple[ConnectionDefinition, ...],
    ) -> None:
        select = self.query_one(f"#{SOURCE_SELECT_IDS[source]}", Select)
        options = (
            [(connection.label, connection.connection_id) for connection in connections]
            if connections
            else [(EMPTY_SOURCE_LABELS[source], EMPTY_CONNECTION_ID)]
        )
        next_value = options[0][1]
        current_value = select.value
        if current_value != Select.BLANK and any(
            option_value == str(current_value) for _, option_value in options
        ):
            next_value = str(current_value)
        select.set_options(options)
        with self.prevent(Select.Changed):
            select.value = next_value

    def set_selected_connection_summary(self, summary: str) -> None:
        """Update the connection summary shown under the source picker."""
        self.query_one("#connection-selection-status", Static).update(summary)

    def set_auth_source_status(
        self, source_description: str, tone: str = "muted"
    ) -> None:
        """Update the auth-source summary shown on the connect screen."""
        status = self.query_one("#auth-source-status", Static)
        status.update(f"Auth source: {source_description}")
        status.remove_class("status-warning")
        if tone == "warning":
            status.add_class("status-warning")

    def _select_radio_button(self, radio_set_id: str, button_id: str) -> None:
        """Synchronously select a single radio button within a radio set."""
        radio_set = self.query_one(f"#{radio_set_id}", RadioSet)
        buttons = list(radio_set.query(RadioButton))
        button = self.query_one(f"#{button_id}", RadioButton)
        with radio_set.prevent(RadioButton.Changed, RadioSet.Changed):
            for candidate in buttons:
                candidate.value = candidate is button
        radio_set._pressed_button = button
        radio_set._selected = buttons.index(button)

    def _set_launch_mode_start_fresh_selected(self) -> None:
        self._select_radio_button("launch-mode-selector", "launch-mode-fresh")

    def _set_launch_mode_resume_selected(self) -> None:
        self._select_radio_button("launch-mode-selector", "launch-mode-resume")

    def _set_auth_mode_default_selected(self) -> None:
        self._select_radio_button("auth-mode-selector", "auth-mode-default")
        self.query_one("#auth-panel", AuthPanel).add_class("hidden")

    def _set_auth_mode_override_selected(self) -> None:
        self._select_radio_button("auth-mode-selector", "auth-mode-override")
        self.query_one("#auth-panel", AuthPanel).remove_class("hidden")

    def get_launch_mode(self) -> WorkspaceLaunchMode:
        if self.query_one("#launch-mode-resume", RadioButton).value:
            return WorkspaceLaunchMode.RESUME_SESSION
        return WorkspaceLaunchMode.START_FRESH

    def set_launch_mode(self, launch_mode: WorkspaceLaunchMode) -> None:
        if launch_mode == WorkspaceLaunchMode.RESUME_SESSION:
            self._set_launch_mode_resume_selected()
            return
        self._set_launch_mode_start_fresh_selected()

    def get_auth_mode(self) -> WorkspaceAuthMode:
        if self.query_one("#auth-mode-override", RadioButton).value:
            return WorkspaceAuthMode.OVERRIDE
        return WorkspaceAuthMode.USE_CONNECTION_DEFAULT

    def set_auth_mode(self, auth_mode: WorkspaceAuthMode) -> None:
        if auth_mode == WorkspaceAuthMode.OVERRIDE:
            self._set_auth_mode_override_selected()
            return
        self._set_auth_mode_default_selected()

    def set_saved_conversation(
        self,
        conversation: SavedConversation | None,
        warning: str | None = None,
    ) -> None:
        status = self.query_one("#conversation-status", Static)
        container = self.query_one("#launch-mode-container", Vertical)
        status.remove_class("status-warning")

        if warning:
            container.add_class("hidden")
            self.set_launch_mode(WorkspaceLaunchMode.START_FRESH)
            status.update(f"Conversation: {warning}")
            status.add_class("status-warning")
            return

        if conversation is None:
            container.add_class("hidden")
            self.set_launch_mode(WorkspaceLaunchMode.START_FRESH)
            status.update("Conversation: start fresh")
            return

        was_hidden = container.has_class("hidden")
        container.remove_class("hidden")
        task_suffix = ""
        if conversation.task_id:
            task_suffix = f" · last task {summarize_identifier(conversation.task_id)}"
        status.update(
            "Conversation: saved context "
            f"{summarize_identifier(conversation.context_id)}{task_suffix}"
        )
        if was_hidden:
            self.set_launch_mode(WorkspaceLaunchMode.RESUME_SESSION)

    def set_status(self, message: str, tone: str = "muted") -> None:
        """Update the connect status line."""
        status = self.query_one("#connect-status", Static)
        status.update(message)
        status.remove_class("status-warning")
        status.remove_class("status-error")
        if tone == "warning":
            status.add_class("status-warning")
        elif tone == "error":
            status.add_class("status-error")

    def get_selected_connection(self) -> ConnectionDefinition | None:
        """Return the currently selected configured connection, if any."""
        source = self.get_active_source()
        if source == ConnectionSource.MANUAL:
            return None

        select = self.query_one(f"#{SOURCE_SELECT_IDS[source]}", Select)
        if select.value == Select.BLANK:
            return None
        return self._connections_by_id.get(str(select.value))

    def get_url(self) -> str:
        """Get the current agent URL from the active source selection."""
        active_source = self.get_active_source()
        if active_source == ConnectionSource.MANUAL:
            return self.query_one("#manual-agent-url", Input).value.strip()
        connection = self.get_selected_connection()
        return connection.agent_url if connection else ""

    def get_auth_credentials(self) -> AuthCredentials | None:
        return self.query_one("#auth-panel", AuthPanel).get_credentials()

    def set_auth_credentials(self, credentials: AuthCredentials | None) -> None:
        auth_panel = self.query_one("#auth-panel", AuthPanel)
        auth_panel.clear()
        if credentials is None:
            return

        if credentials.auth_type == AuthType.BEARER and credentials.value:
            auth_panel.set_bearer_token(credentials.value)
        elif credentials.auth_type == AuthType.API_KEY:
            auth_panel.set_api_key(
                credentials.value,
                credentials.header_name or "X-API-Key",
            )
        elif (
            credentials.auth_type == AuthType.MTLS
            and credentials.cert_path
            and credentials.key_path
        ):
            auth_panel.set_mtls(
                credentials.cert_path,
                credentials.key_path,
                credentials.ca_cert_path,
            )

        auth_panel.set_custom_headers(credentials.custom_headers)


class RemoteLiveView(Container):
    """Post-connect live workspace view."""

    def compose(self) -> ComposeResult:
        with Container(id="live-stage", classes="workspace-live-layout"):
            with Vertical(id="workspace-meta"):
                yield Static("", id="workspace-summary", classes="panel")
                yield AgentCardPanel(id="agent-card-container", classes="panel")

            with Vertical(id="workspace-main"):
                yield TabbedMessagesPanel(id="messages-container", classes="panel")
                yield InputPanel(id="input-container", classes="panel")

    def update_connection_summary(
        self,
        agent_name: str,
        agent_url: str,
        connection_summary: str,
        auth_source: str,
        context_id: str | None = None,
        conversation_summary: str | None = None,
    ) -> None:
        lines = [
            f"Agent: {agent_name}",
            f"Connection: {connection_summary}",
            f"URL: {agent_url}",
            f"Auth: {auth_source}",
        ]
        if context_id:
            lines.append(f"Context: {summarize_identifier(context_id)}")
        if conversation_summary:
            lines.append(f"Conversation: {conversation_summary}")
        self.query_one("#workspace-summary", Static).update("\n".join(lines))

    def agent_card_panel(self) -> AgentCardPanel:
        return self.query_one("#agent-card-container", AgentCardPanel)

    def messages_panel(self) -> TabbedMessagesPanel:
        return self.query_one("#messages-container", TabbedMessagesPanel)

    def input_panel(self) -> InputPanel:
        return self.query_one("#input-container", InputPanel)


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
        yield RemoteConnectView(self.title)

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
        self._load_connection_catalog()
        connect_view = self._get_connect_view()
        connect_view.set_auth_mode(WorkspaceAuthMode.USE_CONNECTION_DEFAULT)
        self.state.auth_mode = connect_view.get_auth_mode()

        if self._initial_bearer_token:
            connect_view.set_auth_mode(WorkspaceAuthMode.OVERRIDE)
            with self._suppressing_auth_events():
                connect_view.set_auth_credentials(
                    AuthCredentials(
                        auth_type=AuthType.BEARER,
                        value=self._initial_bearer_token,
                    )
                )
            self.state.auth_mode = WorkspaceAuthMode.OVERRIDE

        self._refresh_connect_selection()
        self._suspend_connect_events = False

    async def on_unmount(self) -> None:
        if self.http_client:
            await self.http_client.aclose()

    def _get_connect_view(self) -> RemoteConnectView:
        return self.query_one(RemoteConnectView)

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
            summary = (
                f"Connection: {source_label} · {selected_connection.label}\n"
                f"URL: {selected_connection.agent_url}"
            )
        elif active_source == ConnectionSource.MANUAL:
            if agent_url:
                summary = f"Connection: Manual URL\nURL: {agent_url}"
            else:
                summary = "Connection: Manual URL\nURL: not set"
        else:
            summary = (
                f"Connection: {source_label}\n{EMPTY_SOURCE_LABELS[active_source]}"
            )

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
        session = next(
            (
                existing_session
                for existing_session in get_session_store().list_all()
                if existing_session.agent_url == agent_url
            ),
            None,
        )
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
            tone="warning" if warning else "muted",
        )

    def _refresh_live_summary(self) -> None:
        live_view = self._try_get_live_view()
        if (
            live_view is None
            or self.current_agent_url is None
            or self.current_agent_card is None
        ):
            return

        auth_source = self.state.auth_source
        if self.state.auth_mode == WorkspaceAuthMode.OVERRIDE:
            manual_credentials = live_view.messages_panel().get_auth_credentials()
            auth_source = (
                "manual override"
                if manual_credentials is not None
                else "manual override (none)"
            )

        live_view.update_connection_summary(
            agent_name=self.current_agent_card.name,
            agent_url=self.current_agent_url,
            connection_summary=self.state.connection_summary,
            auth_source=auth_source,
            context_id=self.current_context_id,
            conversation_summary=self._conversation_summary(),
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
        if self.http_client:
            await self.http_client.aclose()

        self.http_client = build_http_client(credentials=credentials)
        logger.info("Connecting workspace %s to %s", self.workspace_id, agent_url)
        self._agent_service = A2AService(
            self.http_client,
            agent_url,
            credentials=credentials,
        )
        return await self._agent_service.get_card()

    async def _show_live_view(self, warning: str | None = None) -> None:
        agent_card = self.current_agent_card
        assert agent_card is not None

        await self.remove_children()
        live_view = RemoteLiveView()
        await self.mount(live_view)

        live_view.agent_card_panel().update_card(agent_card)
        live_view.update_connection_summary(
            agent_name=agent_card.name,
            agent_url=self.current_agent_url or "",
            connection_summary=self.state.connection_summary,
            auth_source=self.state.auth_source,
            context_id=self.current_context_id,
            conversation_summary=self._conversation_summary(),
        )
        live_view.messages_panel().load_logs(self._log_lines)
        with self._suppressing_auth_events():
            if self.state.auth_mode == WorkspaceAuthMode.OVERRIDE:
                live_view.messages_panel().set_auth_credentials(
                    self.state.connected_credentials
                )
            else:
                live_view.messages_panel().set_auth_credentials(None)

        await self._hydrate_resumed_history(live_view)

        if warning:
            live_view.messages_panel().add_system_message(warning)
        live_view.messages_panel().add_system_message(
            f"Conversation: {self._conversation_summary()}"
        )
        live_view.messages_panel().add_system_message(f"Connected to {agent_card.name}")
        live_view.input_panel().focus_input()

    @on(TabbedContent.TabActivated, "#connection-source-content")
    def _handle_connection_source_changed(self) -> None:
        if self.is_connected or self._suspend_connect_events:
            return
        self._refresh_connect_selection()

    @on(
        Select.Changed,
        "#repository-connections, #global-connections, #recent-connections",
    )
    def _handle_connection_selection_changed(self) -> None:
        if self.is_connected or self._suspend_connect_events:
            return
        self._refresh_connect_selection()

    @on(Input.Changed, "#manual-agent-url")
    def _handle_manual_url_changed(self) -> None:
        if self.is_connected or self._suspend_connect_events:
            return
        self._refresh_connect_selection()

    @on(RadioSet.Changed, "#auth-mode-selector")
    def _handle_connect_auth_mode_changed(self) -> None:
        if self.is_connected or self._suspend_connect_events:
            return
        connect_view = self._get_connect_view()
        self.state.auth_mode = connect_view.get_auth_mode()
        connect_view.set_auth_mode(self.state.auth_mode)
        self._refresh_connect_auth_source_status()

    @on(RadioSet.Changed, "#auth-type-selector")
    @on(
        Input.Changed,
        "#api-key-input, #api-key-header-input, #bearer-token-input, "
        "#custom-headers-input, #mtls-cert-input, #mtls-key-input, #mtls-ca-input",
    )
    def _handle_auth_field_changed(self) -> None:
        if self._is_syncing_auth_panel:
            return

        if self.is_connected:
            self.state.auth_mode = WorkspaceAuthMode.OVERRIDE
            self._refresh_live_summary()
            return

        connect_view = self._get_connect_view()
        if connect_view.get_auth_mode() != WorkspaceAuthMode.OVERRIDE:
            connect_view.set_auth_mode(WorkspaceAuthMode.OVERRIDE)
        self.state.auth_mode = WorkspaceAuthMode.OVERRIDE
        self._refresh_connect_auth_source_status()

    @on(Button.Pressed, "#connect-btn")
    async def handle_connect_button(self) -> None:
        if self.is_connected:
            return

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
                tone="warning" if warning else "muted",
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

        except Exception as error:
            logger.error(
                "Error sending message from %s: %s",
                self.workspace_id,
                error,
                exc_info=True,
            )
            messages_panel.add_system_message(f"Error: {error!s}")


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
        await switcher.mount(workspace)

        tabs = self.query_one("#workspace-tabs", Tabs)
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

    def action_previous_workspace(self) -> None:
        self.query_one("#workspace-tabs", Tabs).action_previous_tab()

    def action_next_workspace(self) -> None:
        self.query_one("#workspace-tabs", Tabs).action_next_tab()
