"""Per-server tab controller."""

from __future__ import annotations

import atexit
import asyncio
import contextlib
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Generator
from typing import Any
from urllib.parse import urlparse

import httpx
from a2a.client.errors import A2AClientError
from a2a.types import AgentCard, Message as A2AMessage, Role, Task, TaskState
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
    DEFAULT_HANDLER_AGENT_URL,
    ServerCatalog,
    ServerDefinition,
    ServerSource,
    is_default_handler_agent_server,
    load_server_catalog,
    resolve_server_credentials,
)
from a2a_handler.server import DEFAULT_OLLAMA_MODEL, check_ollama_model
from a2a_handler.service import (
    A2AService,
    card_protocol_version,
    extract_text_from_message_parts,
    is_terminal,
    recommend_auth_from_card,
    response_context_id,
    response_task_id,
    response_state,
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

_DEFAULT_HANDLER_AGENT_HOST = "127.0.0.1"
_DEFAULT_HANDLER_AGENT_PORT = 8000
_HANDLER_AGENT_PORT_ATTEMPTS = 20
_HANDLER_AGENT_SHUTDOWN_TIMEOUT_SECONDS = 3
_handler_agent_process: subprocess.Popen | None = None
_handler_agent_process_url: str | None = None


def _handler_agent_model() -> str:
    """Return the Ollama model used by the auto-started Handler agent."""
    return os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def _raise_if_handler_agent_model_unavailable() -> None:
    """Fail early with an actionable message when the built-in agent can't run."""
    model = _handler_agent_model()
    if shutil.which("ollama") is None:
        raise RuntimeError(
            "Handler's built-in agent requires Ollama, but the Ollama CLI was not found. "
            "Install Ollama, then run `ollama pull "
            f"{model}` or `handler server run agent` before connecting."
        )
    if not check_ollama_model(model):
        raise RuntimeError(
            "Handler's built-in agent requires the Ollama model "
            f"'{model}'. Run `ollama pull {model}` or `handler server run agent` "
            "before connecting."
        )


def shutdown_default_handler_agent() -> None:
    """Stop the auto-started Handler embedded-agent process, if any.

    The TUI only owns the process it launched itself. If the user already had a
    server listening on the default URL, no process is stored and this is a no-op.
    """
    global _handler_agent_process, _handler_agent_process_url
    process = _handler_agent_process
    if process is None or process.poll() is not None:
        _handler_agent_process = None
        _handler_agent_process_url = None
        return

    logger.info("Stopping auto-started Handler embedded agent")
    process.terminate()
    try:
        process.wait(timeout=_HANDLER_AGENT_SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        logger.warning("Handler embedded agent did not stop; killing process")
        process.kill()
        try:
            process.wait(timeout=_HANDLER_AGENT_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            logger.error("Handler embedded agent process did not exit after kill")
            return

    _handler_agent_process = None
    _handler_agent_process_url = None


atexit.register(shutdown_default_handler_agent)


async def _handler_agent_card_available(agent_url: str) -> bool:
    """Return whether an A2A agent card is reachable at the given URL."""
    try:
        async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
            response = await client.get(
                f"{agent_url.rstrip('/')}/.well-known/agent-card.json"
            )
            return response.status_code == 200
    except httpx.HTTPError:
        return False


def _handler_agent_url(host: str, port: int) -> str:
    """Build the local URL for an auto-started Handler agent."""
    return f"http://{host}:{port}"


def _port_is_available(host: str, port: int) -> bool:
    """Return whether the local host/port can be bound by a new server."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
    except OSError:
        return False
    return True


def _first_available_handler_agent_port(start_port: int) -> int | None:
    """Return the first available local embedded-agent port at or above start."""
    for port in range(start_port, start_port + _HANDLER_AGENT_PORT_ATTEMPTS):
        if _port_is_available(_DEFAULT_HANDLER_AGENT_HOST, port):
            return port
    return None


async def ensure_default_handler_agent_running(
    agent_url: str = DEFAULT_HANDLER_AGENT_URL,
) -> tuple[bool, str]:
    """Start Handler's embedded agent if it is not already reachable.

    Returns ``(started, agent_url)`` where ``started`` is True when this call
    launched the server process. The returned URL may use a later port when the
    preferred default port is already in use by another local process.
    """
    global _handler_agent_process, _handler_agent_process_url

    if await _handler_agent_card_available(agent_url):
        return False, agent_url

    if _handler_agent_process is not None:
        if _handler_agent_process.poll() is None and _handler_agent_process_url:
            return False, _handler_agent_process_url
        _handler_agent_process = None
        _handler_agent_process_url = None

    _raise_if_handler_agent_model_unavailable()

    parsed_url = urlparse(agent_url)
    start_port = parsed_url.port or _DEFAULT_HANDLER_AGENT_PORT
    port = _first_available_handler_agent_port(start_port)
    if port is None:
        last_port = start_port + _HANDLER_AGENT_PORT_ATTEMPTS - 1
        raise RuntimeError(
            "Handler's embedded agent could not find an available local port "
            f"between {start_port} and {last_port}."
        )

    launch_url = _handler_agent_url(parsed_url.hostname or "localhost", port)

    if _handler_agent_process is None or _handler_agent_process.poll() is not None:
        logger.info("Auto-starting Handler embedded agent at %s", launch_url)
        _handler_agent_process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from a2a_handler.cli import main; main()",
                "server",
                "run",
                "agent",
                "--host",
                _DEFAULT_HANDLER_AGENT_HOST,
                "--port",
                str(port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _handler_agent_process_url = launch_url

    for _ in range(40):
        if _handler_agent_process.poll() is not None:
            break
        if await _handler_agent_card_available(launch_url):
            return True, launch_url
        await asyncio.sleep(0.25)

    raise RuntimeError(
        "Handler's embedded agent did not become ready. "
        "Run `handler server run agent` in a terminal to see startup details."
    )


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

    def _load_server_catalog(self, *, sync_selected_auth: bool = True) -> None:
        self._server_catalog = load_server_catalog()
        self._server_credentials = {}
        self._server_warnings = {}
        self._servers_by_id = {}

        configured_servers = (
            *self._server_catalog.repository_servers,
            *self._server_catalog.global_servers,
        )
        configured_servers_by_url: dict[str, ServerDefinition] = {}
        for server_def in configured_servers:
            self._servers_by_id[server_def.server_id] = server_def
            configured_servers_by_url.setdefault(server_def.agent_url, server_def)
            credentials, warning = resolve_server_credentials(server_def)
            if credentials:
                self._server_credentials[server_def.server_id] = credentials
            if warning:
                self._server_warnings[server_def.server_id] = warning

        recent_servers: list[ServerDefinition] = []
        for session in get_session_store().list_all():
            if len(recent_servers) >= RECENT_SERVER_LIMIT:
                break
            if not session.last_used_at:
                continue
            saved_conversation, _warning = resolve_saved_conversation(
                session,
                session.agent_url,
            )
            if saved_conversation is None:
                continue
            base_server = configured_servers_by_url.get(session.agent_url)
            recent_server = build_recent_server(
                session.agent_url,
                base_server=base_server,
            )
            recent_servers.append(recent_server)
            self._servers_by_id[recent_server.server_id] = recent_server
            if base_server is None:
                continue
            credentials = self._server_credentials.get(base_server.server_id)
            warning = self._server_warnings.get(base_server.server_id)
            if credentials:
                self._server_credentials[recent_server.server_id] = credentials
            if warning:
                self._server_warnings[recent_server.server_id] = warning

        connection_bar = self._get_connection_bar()
        connection_bar.set_server_catalog(
            repository_servers=self._server_catalog.repository_servers,
            global_servers=self._server_catalog.global_servers,
            recent_servers=tuple(recent_servers),
        )

        selected = connection_bar.get_selected_server()
        if sync_selected_auth and selected is not None:
            self._sync_auth_to_server(selected.server_id)

    def refresh_server_catalog(self) -> None:
        """Reload server definitions while preserving the current picker intent."""
        connection_bar = self._get_connection_bar()
        previous_selected = connection_bar.get_selected_server()
        manual_selected = connection_bar._is_manual_selected()
        manual_url = connection_bar.query_one("#manual-agent-url", Input).value
        manual_credentials = None
        if manual_selected:
            manual_credentials = (
                self._get_server_view().messages_panel().get_auth_credentials()
            )

        self._load_server_catalog(sync_selected_auth=False)

        if manual_selected:
            self._select_manual_url(manual_url)
            with self._suppressing_auth_events():
                self._get_server_view().messages_panel().set_auth_credentials(
                    manual_credentials
                )
        elif previous_selected is not None:
            restored = self._find_matching_server(
                previous_selected, allow_any_source=True
            )
            if restored is not None:
                self._select_server(restored)
            else:
                selected = connection_bar.get_selected_server()
                if selected is not None:
                    self._sync_auth_to_server(selected.server_id)

        if self.state.connected_server_def is not None:
            self.state.connected_server_def = self._find_matching_server(
                self.state.connected_server_def
            )
        self._refresh_status_badges()

    def _find_matching_server(
        self,
        previous_server: ServerDefinition,
        *,
        allow_any_source: bool = False,
    ) -> ServerDefinition | None:
        exact = self._servers_by_id.get(previous_server.server_id)
        if exact is not None:
            return exact

        for server_def in self._servers_by_id.values():
            if (
                server_def.source == previous_server.source
                and server_def.agent_url == previous_server.agent_url
            ):
                return server_def

        if allow_any_source:
            for server_def in self._servers_by_id.values():
                if server_def.agent_url == previous_server.agent_url:
                    return server_def
        return None

    def _select_server(self, server_def: ServerDefinition) -> None:
        """Select a specific configured server in the picker."""
        connection_bar = self._get_connection_bar()
        select = connection_bar.query_one("#server-select", Select)
        with connection_bar.prevent(Select.Changed):
            select.value = server_def.server_id
        connection_bar._sync_manual_input()
        self._sync_auth_to_server(server_def.server_id)

    def get_selected_workspace_server(self) -> ServerDefinition | None:
        """Return the repo-local server selected in the picker, if any."""
        selected = self._get_connection_bar().get_selected_server()
        if selected is not None and selected.source == ServerSource.REPOSITORY:
            return selected
        if selected is not None and selected.source == ServerSource.RECENT:
            for server_def in self._server_catalog.repository_servers:
                if server_def.agent_url == selected.agent_url:
                    return server_def
        if (
            self.state.connected_server_def is not None
            and self.state.connected_server_def.source == ServerSource.REPOSITORY
        ):
            return self.state.connected_server_def
        return None

    def get_saved_session_target(self) -> tuple[str, str] | None:
        """Return the current saved-session target URL and label, if one exists."""
        session_store = get_session_store()
        connection_bar = self._get_connection_bar()
        selected = connection_bar.get_selected_server()
        if selected is not None and session_store.find(selected.agent_url) is not None:
            return selected.agent_url, selected.label

        if (
            self.state.agent_url is not None
            and session_store.find(self.state.agent_url) is not None
        ):
            if self.state.connected_server_def is not None:
                label = self.state.connected_server_def.label
            elif self.state.agent_card is not None:
                label = self.state.agent_card.name
            else:
                label = self.state.agent_url
            return self.state.agent_url, label

        manual_url = connection_bar.query_one("#manual-agent-url", Input).value.strip()
        if manual_url and session_store.find(manual_url) is not None:
            return manual_url, manual_url

        return None

    def forget_saved_session(self, agent_url: str) -> None:
        """Forget a saved session and refresh recent-server picker state."""
        get_session_store().clear(agent_url)
        self.refresh_server_catalog()

    def _connection_source_label(
        self,
        connected_server: ServerDefinition | None,
    ) -> str:
        """Return a short label for where the live connection came from."""
        if connected_server is None:
            return "Direct URL"
        if is_default_handler_agent_server(connected_server):
            return "Embedded Server"
        source_labels = {
            ServerSource.REPOSITORY: "Repository Server",
            ServerSource.GLOBAL: "User Server",
            ServerSource.RECENT: "Recent Session",
            ServerSource.MANUAL: "Direct URL",
        }
        return source_labels[connected_server.source]

    def _auth_badge_label(self, credentials: AuthCredentials | None) -> str:
        """Return a concise auth badge label for the active credentials."""
        if credentials is None:
            return ""
        if credentials.auth_type == AuthType.MTLS:
            return "mTLS"
        if credentials.auth_type == AuthType.OAUTH2:
            return "OAuth 2.0"
        if credentials.auth_type == AuthType.GOOGLE:
            return "Google Cloud"
        if credentials.auth_type == AuthType.API_KEY:
            return "API Key"
        if credentials.auth_type == AuthType.BEARER:
            if credentials.value:
                return "Bearer"
            if credentials.custom_headers:
                return "Headers"
        return ""

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

    def _selection_resumes_saved_context(
        self,
        selected_server: ServerDefinition | None,
    ) -> bool:
        """Recent entries are explicit resume targets; other selections start fresh."""
        return (
            selected_server is not None
            and selected_server.source == ServerSource.RECENT
        )

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
        conversation_summary: str,
        warning: str | None = None,
        saved_conversation: SavedConversation | None = None,
    ) -> None:
        agent_card = self.state.agent_card
        assert agent_card is not None

        server_view = self._get_server_view()
        await server_view.reset_session()
        server_view.agent_card_panel().update_card(agent_card)

        if saved_conversation is not None:
            await self._hydrate_resumed_history(server_view, saved_conversation)

        if warning:
            server_view.messages_panel().add_system_message(warning)
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

    async def handle_connect_button(self) -> None:
        connection_bar = self._get_connection_bar()
        selected_server = connection_bar.get_selected_server()
        agent_url = connection_bar.get_url()
        should_resume_session = self._selection_resumes_saved_context(selected_server)

        messages_panel = self._get_server_view().messages_panel()
        previous_state = ServerState(
            mode=self.state.mode,
            agent_card=self.state.agent_card,
            agent_url=self.state.agent_url,
            current_context_id=self.state.current_context_id,
            current_task_id=self.state.current_task_id,
            connected_server_def=self.state.connected_server_def,
        )

        if not agent_url:
            if connection_bar._is_manual_selected():
                messages_panel.add_system_message("Please enter an agent URL")
            else:
                messages_panel.add_system_message("Choose a server or select URL")
            return

        try:
            validate_agent_url(agent_url)
        except InputValidationError as error:
            messages_panel.add_system_message(self._build_connect_error_message(error))
            return

        saved_conversation: SavedConversation | None = None
        if should_resume_session:
            saved_conversation, session_warning = resolve_saved_conversation(
                get_session_store().find(agent_url),
                agent_url,
            )
            if session_warning:
                messages_panel.add_system_message(session_warning)
                return
            if saved_conversation is None:
                messages_panel.add_system_message(
                    "No saved context is available for this recent session."
                )
                return

        connection_bar.set_status(f"Connecting to {agent_url}...")

        try:
            credentials = messages_panel.get_auth_credentials()
            startup_message: str | None = None

            if selected_server is not None and is_default_handler_agent_server(
                selected_server
            ):
                connection_bar.set_status("Starting Handler agent...", tone="accent")
                started, agent_url = await ensure_default_handler_agent_running(
                    agent_url
                )
                if started:
                    startup_message = (
                        f"Started Handler's embedded agent at {agent_url}."
                    )
                connection_bar.set_status(f"Connecting to {agent_url}...")

            agent_card = await self._connect_to_agent(agent_url, credentials)
            context_id: str | None = None
            resumed_task_id: str | None = None
            if saved_conversation is not None:
                assert saved_conversation is not None
                context_id = saved_conversation.context_id
                resumed_task_id = saved_conversation.task_id

            self.state.agent_card = agent_card
            self.state.agent_url = agent_url
            self.state.current_context_id = context_id
            self.state.current_task_id = resumed_task_id
            self.state.connected_server_def = selected_server
            self.state.mode = ServerConnectionMode.CONNECTED

            if credentials is None:
                recommendation = recommend_auth_from_card(agent_card)
                if recommendation is not None:
                    messages_panel.set_auth_recommendation(recommendation)
                    self.notify(
                        f"{agent_card.name} declares {recommendation.detail}. "
                        "Configure it in the Auth tab and reconnect.",
                        severity="warning",
                    )

            await self._apply_connected_ui(
                conversation_summary=(
                    "resumed recent session"
                    if saved_conversation is not None
                    else "fresh server context"
                ),
                warning=startup_message,
                saved_conversation=saved_conversation,
            )
            self._persist_session_state()
            self.post_message(self.TitleChanged(self.server_id, agent_card.name))

        except Exception as error:
            logger.error(
                "Connection failed for %s: %s",
                self.server_id,
                error,
                exc_info=True,
            )
            messages_panel.add_system_message(f"Connection failed: {error!s}")
            if previous_state.mode == ServerConnectionMode.CONNECTED:
                self.state = previous_state
                self._refresh_status_badges()
            else:
                self.state.mode = ServerConnectionMode.DISCONNECTED
                self.state.agent_card = None
                self.state.agent_url = None
                self.state.current_task_id = None
                self.state.current_context_id = None
                self.state.connected_server_def = None
                self._refresh_status_badges()

    @on(Button.Pressed, "#connect-btn")
    async def _handle_connect_pressed(self) -> None:
        await self.handle_connect_button()

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
        input_panel.set_waiting(True)

        try:
            credentials = messages_panel.get_auth_credentials()
            if credentials is not None:
                self._agent_service.set_credentials(credentials)
            else:
                self._agent_service.clear_credentials()

            self._refresh_status_badges()

            try:
                response = await self._agent_service.send(
                    message_text,
                    context_id=self.state.current_context_id,
                    task_id=self.state.current_task_id,
                )
            except Exception as error:
                if self.state.current_task_id and self._is_uncontinuable_task_error(
                    error
                ):
                    logger.info(
                        "Retrying %s without active task_id %s",
                        self.server_id,
                        self.state.current_task_id,
                    )
                    self._clear_current_task_id()
                    messages_panel.add_system_message(
                        "Saved task can no longer accept messages; retrying with the saved context only."
                    )
                    response = await self._agent_service.send(
                        message_text,
                        context_id=self.state.current_context_id,
                        task_id=None,
                    )
                else:
                    raise

            ctx_id = response_context_id(response)
            if ctx_id:
                self.state.current_context_id = ctx_id
            next_task_id = response_task_id(response)
            self.state.current_task_id = None if is_terminal(response) else next_task_id
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
        finally:
            if self.is_connected:
                input_panel.set_waiting(False)
                input_panel.focus_input()

    def _refresh_status_badges(self) -> None:
        server_view = self._try_get_server_view()
        if server_view is None:
            return

        if self.state.agent_url is None or self.state.agent_card is None:
            self._show_disconnected_state()
            return

        try:
            auth_credentials = server_view.messages_panel().get_auth_credentials()
        except InputValidationError:
            auth_credentials = None

        server_view.connection_bar().set_connected_status(
            agent_name=self.state.agent_card.name,
            source_label=self._connection_source_label(self.state.connected_server_def),
            auth_label=self._auth_badge_label(auth_credentials),
            protocol_version=card_protocol_version(self.state.agent_card),
            agent_version=self.state.agent_card.version,
        )

    async def start_fresh_conversation(self) -> None:
        """Reset the current live connection to a fresh context and task."""
        if not self.is_connected or self.state.agent_card is None:
            return

        self.state.current_context_id = None
        self.state.current_task_id = None
        await self._apply_connected_ui(
            conversation_summary="fresh server context",
            warning="Started a fresh conversation on the current server.",
        )
        self._persist_session_state()

    def _persist_session_state(self) -> None:
        if self.state.agent_url is None:
            return
        get_session_store().set_conversation(
            self.state.agent_url,
            self.state.current_context_id,
            self.state.current_task_id,
        )

    def _clear_current_task_id(self) -> None:
        """Drop the active task ID while keeping the current context."""
        if self.state.current_task_id is None:
            return
        self.state.current_task_id = None
        self._persist_session_state()

    def _is_uncontinuable_task_error(self, error: Exception) -> bool:
        """Return True when the server rejects continuing the current task."""
        if not isinstance(error, A2AClientError):
            return False
        message = str(error).lower()
        if "task" in message and (
            "does not exist" in message or "not found" in message
        ):
            return True
        terminal_markers = (
            "terminal state",
            "cannot accept further messages",
            "already completed",
            "task is completed",
        )
        return any(marker in message for marker in terminal_markers)

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

        if message.role == Role.ROLE_AGENT:
            messages_panel.add_agent_message(message)
            return

        if message.role == Role.ROLE_USER:
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
            if self.state.current_task_id == saved_conversation.task_id:
                self._clear_current_task_id()
            server_view.messages_panel().add_system_message(
                "Resumed saved context, but the saved task could not be loaded. New messages will continue without that task ID."
            )
            return

        self._load_task_into_live_view(server_view, task)
        if response_state(task) in {
            TaskState.TASK_STATE_COMPLETED,
            TaskState.TASK_STATE_FAILED,
            TaskState.TASK_STATE_CANCELED,
            TaskState.TASK_STATE_REJECTED,
        }:
            if self.state.current_task_id == task.id:
                self._clear_current_task_id()
