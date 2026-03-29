"""Workspace shell and per-remote workspace state for the TUI."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import httpx
from a2a.types import AgentCard
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message as TextualMessage
from textual.widgets import (
    Button,
    ContentSwitcher,
    Input,
    RadioSet,
    Select,
    Static,
    Tab,
    Tabs,
)

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import InputValidationError, validate_agent_url
from a2a_handler.profiles import (
    ConnectionProfile,
    load_all_profiles,
    resolve_profile_credentials,
)
from a2a_handler.service import A2AService
from a2a_handler.session import get_credentials, get_session_store
from a2a_handler.tui.components import (
    AgentCardPanel,
    AuthPanel,
    InputPanel,
    TabbedMessagesPanel,
)

logger = get_logger(__name__)

CUSTOM_TARGET_ID = "custom"
DEFAULT_HTTP_TIMEOUT_SECONDS = 120


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


@dataclass(frozen=True, slots=True)
class ConnectionTarget:
    """A selectable remote target for a workspace."""

    target_id: str
    label: str
    agent_url: str
    profile_name: str | None = None


class RemoteConnectView(Container):
    """Centered pre-connect view for a remote workspace."""

    def __init__(self, workspace_title: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._workspace_title = workspace_title
        self._connection_targets: dict[str, ConnectionTarget] = {}
        self._selected_target_id = CUSTOM_TARGET_ID

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="connect-scroll"):
            with Container(id="connect-stage"):
                with Container(classes="connect-canvas"):
                    with Vertical(id="connect-card"):
                        yield Static("Remote Workspace", classes="connect-eyebrow")
                        yield Static(self._workspace_title, id="connect-title")
                        yield Static(
                            "Choose a profile, recent target, or custom URL before opening the live workspace.",
                            id="connect-subtitle",
                        )
                        with Vertical(id="connect-form"):
                            yield Select(
                                [("Custom URL", CUSTOM_TARGET_ID)],
                                allow_blank=False,
                                value=CUSTOM_TARGET_ID,
                                id="connection-target",
                            )
                            yield Input(
                                placeholder="http://localhost:8000",
                                value="http://localhost:8000",
                                id="agent-url",
                            )
                            yield Static("Auth source: none", id="auth-source-status")
                            yield AuthPanel(id="auth-panel")
                            with Horizontal(id="connect-actions"):
                                yield Static("", id="connect-status")
                                yield Button("CONNECT", id="connect-btn")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Press connect when any connect-form input is submitted."""
        connect_button = self.query_one("#connect-btn", Button)
        self.post_message(Button.Pressed(connect_button))

    @on(Select.Changed, "#connection-target")
    def _on_connection_target_changed(self, event: Select.Changed) -> None:
        if event.value == Select.BLANK:
            return

        target_id = str(event.value)
        self._selected_target_id = target_id
        target = self._connection_targets.get(target_id)
        if target:
            self.query_one("#agent-url", Input).value = target.agent_url

    @on(Input.Changed, "#agent-url")
    def _on_agent_url_changed(self, event: Input.Changed) -> None:
        selected_target = self._connection_targets.get(self._selected_target_id)
        if selected_target and selected_target.agent_url == event.value.strip():
            return

        if self._selected_target_id == CUSTOM_TARGET_ID:
            return

        self._selected_target_id = CUSTOM_TARGET_ID
        self.query_one("#connection-target", Select).value = CUSTOM_TARGET_ID

    def set_connection_targets(
        self,
        profile_urls: dict[str, str],
        saved_urls: list[str],
    ) -> None:
        """Populate selector options with profile and recent targets."""
        targets = {
            CUSTOM_TARGET_ID: ConnectionTarget(
                target_id=CUSTOM_TARGET_ID,
                label="Custom URL",
                agent_url="",
            )
        }
        options: list[tuple[str, str]] = [("Custom URL", CUSTOM_TARGET_ID)]

        for profile_name in sorted(profile_urls):
            target_id = f"profile:{profile_name}"
            label = f"Profile: {profile_name}"
            targets[target_id] = ConnectionTarget(
                target_id=target_id,
                label=label,
                agent_url=profile_urls[profile_name],
                profile_name=profile_name,
            )
            options.append((label, target_id))

        known_profile_urls = set(profile_urls.values())
        for url in saved_urls:
            if url in known_profile_urls:
                continue
            target_id = f"saved:{url}"
            label = f"Recent: {url}"
            targets[target_id] = ConnectionTarget(
                target_id=target_id,
                label=label,
                agent_url=url,
            )
            options.append((label, target_id))

        self._connection_targets = targets

        selector = self.query_one("#connection-target", Select)
        selector.set_options(options)

        current_value = selector.value
        if current_value == Select.BLANK:
            selector.value = CUSTOM_TARGET_ID
            self._selected_target_id = CUSTOM_TARGET_ID
            return

        current_target_id = str(current_value)
        if current_target_id not in targets:
            selector.value = CUSTOM_TARGET_ID
            self._selected_target_id = CUSTOM_TARGET_ID
            return

        self._selected_target_id = current_target_id

    def set_auth_source_status(self, source_description: str) -> None:
        status = self.query_one("#auth-source-status", Static)
        status.update(f"Auth source: {source_description}")

    def set_status(self, message: str, tone: str = "muted") -> None:
        status = self.query_one("#connect-status", Static)
        status.update(message)
        status.remove_class("status-warning")
        status.remove_class("status-error")
        if tone == "warning":
            status.add_class("status-warning")
        elif tone == "error":
            status.add_class("status-error")

    def get_url(self) -> str:
        return self.query_one("#agent-url", Input).value.strip()

    def get_selected_profile_name(self) -> str | None:
        target = self._connection_targets.get(self._selected_target_id)
        return target.profile_name if target else None

    def get_selected_target_id(self) -> str:
        return self._selected_target_id

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
        auth_source: str,
    ) -> None:
        self.query_one("#workspace-summary", Static).update(
            f"Agent: {agent_name}\nURL: {agent_url}\nAuth: {auth_source}"
        )

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
        self.current_agent_card: AgentCard | None = None
        self.current_agent_url: str | None = None
        self.current_context_id: str | None = None
        self.http_client: httpx.AsyncClient | None = None
        self._agent_service: A2AService | None = None
        self._connected_credentials: AuthCredentials | None = None
        self._connected_auth_source = "none"
        self._profiles: dict[str, ConnectionProfile] = {}
        self._profile_credentials: dict[str, AuthCredentials] = {}
        self._profile_warnings: dict[str, str] = {}
        self._initial_bearer_token = initial_bearer_token
        self._manual_auth_override = False
        self._syncing_auth_depth = 0
        self._suspend_target_change_events = False
        self._is_connected = False
        self._log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield RemoteConnectView(self.title)

    @property
    def is_connected(self) -> bool:
        return self._is_connected

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
        self._suspend_target_change_events = True
        self._load_connection_targets()
        self._sync_connect_auth_panel_with_resolved_credentials()

        if self._initial_bearer_token:
            with self._suppressing_auth_events():
                self._get_connect_view().set_auth_credentials(
                    AuthCredentials(
                        auth_type=AuthType.BEARER,
                        value=self._initial_bearer_token,
                    )
                )
            self._manual_auth_override = True

        self._refresh_connect_auth_source_status()
        self._suspend_target_change_events = False

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

    def _load_connection_targets(self) -> None:
        self._profiles = load_all_profiles()
        self._profile_credentials = {}
        self._profile_warnings = {}

        for profile_name, profile in self._profiles.items():
            credentials, warning = resolve_profile_credentials(profile)
            if credentials:
                self._profile_credentials[profile_name] = credentials
            if warning:
                self._profile_warnings[profile_name] = warning
                logger.warning("Profile %s: %s", profile_name, warning)

        profile_urls = {
            profile_name: profile.agent_url
            for profile_name, profile in self._profiles.items()
        }
        saved_urls = sorted(
            {session.agent_url for session in get_session_store().list_all()}
        )

        self._get_connect_view().set_connection_targets(
            profile_urls=profile_urls,
            saved_urls=saved_urls,
        )

    def _resolve_connection_credentials(
        self,
        agent_url: str,
        selected_profile_name: str | None,
        manual_credentials: AuthCredentials | None,
        manual_override: bool = False,
    ) -> tuple[AuthCredentials | None, str, str | None]:
        """Resolve connect-time credentials using the agreed precedence order."""
        if manual_credentials:
            return manual_credentials, "manual (Auth tab)", None
        if manual_override:
            return None, "manual (none)", None

        profile = None
        if selected_profile_name:
            profile = self._profiles.get(selected_profile_name)

        if profile and profile.agent_url == agent_url:
            profile_credentials = self._profile_credentials.get(profile.name)
            if profile_credentials:
                return profile_credentials, f"profile '{profile.name}'", None

            profile_warning = self._profile_warnings.get(profile.name)
            if profile_warning:
                saved_credentials = get_credentials(agent_url)
                if saved_credentials:
                    return (
                        saved_credentials,
                        f"saved (profile '{profile.name}' unavailable)",
                        profile_warning,
                    )
                return None, f"profile '{profile.name}' unavailable", profile_warning

            saved_credentials = get_credentials(agent_url)
            if saved_credentials:
                return (
                    saved_credentials,
                    f"saved (profile '{profile.name}' has no auth)",
                    None,
                )
            return None, f"profile '{profile.name}' (none)", None

        if profile and profile.agent_url != agent_url:
            saved_credentials = get_credentials(agent_url)
            if saved_credentials:
                return (
                    saved_credentials,
                    f"saved (selected profile '{profile.name}' URL differs)",
                    None,
                )
            return None, f"none (selected profile '{profile.name}' URL differs)", None

        saved_credentials = get_credentials(agent_url)
        if saved_credentials:
            return saved_credentials, "saved", None

        return None, "none", None

    def _sync_connect_auth_panel_with_resolved_credentials(self) -> None:
        if self._manual_auth_override:
            return

        connect_view = self._get_connect_view()
        agent_url = connect_view.get_url()
        if not agent_url:
            connect_view.set_auth_credentials(None)
            return

        selected_profile_name = connect_view.get_selected_profile_name()
        resolved_credentials, _, _ = self._resolve_connection_credentials(
            agent_url=agent_url,
            selected_profile_name=selected_profile_name,
            manual_credentials=None,
        )
        with self._suppressing_auth_events():
            connect_view.set_auth_credentials(resolved_credentials)

    def _refresh_connect_auth_source_status(self) -> None:
        connect_view = self._get_connect_view()
        agent_url = connect_view.get_url()
        if not agent_url:
            connect_view.set_auth_source_status("none")
            return

        manual_credentials = connect_view.get_auth_credentials()
        _, source_description, _ = self._resolve_connection_credentials(
            agent_url=agent_url,
            selected_profile_name=connect_view.get_selected_profile_name(),
            manual_credentials=manual_credentials,
            manual_override=self._manual_auth_override,
        )
        connect_view.set_auth_source_status(source_description)

    def _refresh_live_summary(self) -> None:
        live_view = self._try_get_live_view()
        if (
            live_view is None
            or self.current_agent_url is None
            or self.current_agent_card is None
        ):
            return

        auth_source = self._connected_auth_source
        if self._manual_auth_override:
            manual_credentials = live_view.messages_panel().get_auth_credentials()
            auth_source = "manual (Auth tab)" if manual_credentials else "manual (none)"

        live_view.update_connection_summary(
            agent_name=self.current_agent_card.name,
            agent_url=self.current_agent_url,
            auth_source=auth_source,
        )

    def _handle_connection_target_transition(self) -> None:
        connect_view = self._get_connect_view()
        if connect_view.get_selected_target_id() == CUSTOM_TARGET_ID:
            return

        self._manual_auth_override = False
        self._sync_connect_auth_panel_with_resolved_credentials()
        self._refresh_connect_auth_source_status()

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
            auth_source=self._connected_auth_source,
        )
        live_view.messages_panel().load_logs(self._log_lines)
        with self._suppressing_auth_events():
            live_view.messages_panel().set_auth_credentials(self._connected_credentials)
        self._manual_auth_override = False

        if warning:
            live_view.messages_panel().add_system_message(warning)
        live_view.messages_panel().add_system_message(f"Connected to {agent_card.name}")
        live_view.input_panel().focus_input()

    @on(Select.Changed, "#connection-target")
    def _handle_connection_target_changed(self) -> None:
        if self._is_connected or self._suspend_target_change_events:
            return
        self._handle_connection_target_transition()

    @on(Input.Changed, "#agent-url")
    def _handle_agent_url_changed(self) -> None:
        if self._is_connected:
            return

        connect_view = self._get_connect_view()
        if connect_view.get_selected_target_id() != CUSTOM_TARGET_ID:
            self._handle_connection_target_transition()
            return

        self._sync_connect_auth_panel_with_resolved_credentials()
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
        self._manual_auth_override = True
        if self._is_connected:
            self._refresh_live_summary()
        else:
            self._refresh_connect_auth_source_status()

    @on(Button.Pressed, "#connect-btn")
    async def handle_connect_button(self) -> None:
        if self._is_connected:
            return

        connect_view = self._get_connect_view()
        agent_url = connect_view.get_url()

        if not agent_url:
            connect_view.set_status("Please enter an agent URL", tone="warning")
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
            selected_profile_name = connect_view.get_selected_profile_name()
            manual_credentials = (
                connect_view.get_auth_credentials()
                if self._manual_auth_override
                else None
            )
            credentials, source_description, warning = (
                self._resolve_connection_credentials(
                    agent_url=agent_url,
                    selected_profile_name=selected_profile_name,
                    manual_credentials=manual_credentials,
                    manual_override=self._manual_auth_override,
                )
            )
            connect_view.set_auth_source_status(source_description)
            if warning:
                connect_view.set_status(warning, tone="warning")

            agent_card = await self._connect_to_agent(agent_url, credentials)

            self.current_agent_card = agent_card
            self.current_agent_url = agent_url
            self.current_context_id = str(uuid.uuid4())
            self._connected_credentials = credentials
            self._connected_auth_source = source_description
            self._is_connected = True

            await self._show_live_view(warning)
            self.post_message(self.TitleChanged(self.workspace_id, agent_card.name))

        except Exception as error:
            logger.error(
                "Connection failed for %s: %s", self.workspace_id, error, exc_info=True
            )
            connect_view.set_status(f"Connection failed: {error!s}", tone="error")

    @on(Input.Submitted, "#message-input")
    def handle_message_submit(self) -> None:
        if self._is_connected:
            self._send_message()

    @on(Button.Pressed, "#send-btn")
    def handle_send_button(self) -> None:
        if self._is_connected:
            self._send_message()

    @work(exclusive=True)
    async def _send_message(self) -> None:
        live_view = self._try_get_live_view()
        if (
            not self._is_connected
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
            if self._manual_auth_override:
                credentials = messages_panel.get_auth_credentials()
                if credentials is not None:
                    self._agent_service.set_credentials(credentials)
                else:
                    self._agent_service.clear_credentials()
            elif self._connected_credentials is not None:
                self._agent_service.set_credentials(self._connected_credentials)
            else:
                self._agent_service.clear_credentials()

            self._refresh_live_summary()

            send_result = await self._agent_service.send(
                message_text,
                context_id=self.current_context_id,
            )

            if send_result.context_id:
                self.current_context_id = send_result.context_id

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
