"""Main TUI application for Handler.

Provides the Textual-based terminal interface for agent interaction.
"""

import contextlib
import logging
import uuid
from collections.abc import Generator, Iterable
from importlib.metadata import version
from typing import Any

import httpx
from a2a.types import AgentCard
from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.logging import TextualHandler
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, RadioSet, Select

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.common import get_theme, install_tui_log_handler, save_theme
from a2a_handler.profiles import (
    ConnectionProfile,
    load_all_profiles,
    resolve_profile_credentials,
)
from a2a_handler.service import A2AService
from a2a_handler.session import get_credentials, get_session_store
from a2a_handler.tui.components import (
    AgentCardPanel,
    ContactPanel,
    InputPanel,
    TabbedMessagesPanel,
)

__version__ = version("a2a-handler")

logging.basicConfig(
    level="NOTSET",
    handlers=[TextualHandler()],
)
logger = logging.getLogger(__name__)

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


class HandlerTUI(App[Any]):
    """Handler - A2A Agent Management Interface."""

    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("/", "command_palette", "Palette", show=True),
        Binding("ctrl+m", "toggle_maximize", "Maximize", show=True),
    ]

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Show maximize binding only for maximizable panels."""
        if action == "toggle_maximize":
            focused = self.focused
            if focused is None:
                return False
            for panel in (
                self.query_one("#messages-container", TabbedMessagesPanel),
                self.query_one("#agent-card-container", AgentCardPanel),
            ):
                if focused is panel or panel in focused.ancestors:
                    return True
            return False
        return True

    def __init__(self, initial_bearer_token: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.current_agent_card: AgentCard | None = None
        self.http_client: httpx.AsyncClient | None = None
        self.current_context_id: str | None = None
        self.current_agent_url: str | None = None
        self._agent_service: A2AService | None = None
        self._is_maximized: bool = False
        self._initial_bearer_token = initial_bearer_token
        self._profiles: dict[str, ConnectionProfile] = {}
        self._profile_credentials: dict[str, AuthCredentials] = {}
        self._profile_warnings: dict[str, str] = {}
        self._manual_auth_override: bool = False
        self._syncing_auth_depth: int = 0
        self._suspend_target_change_events: bool = False

    def compose(self) -> ComposeResult:
        with Container(id="root-container"):
            with Vertical(id="left-pane"):
                yield ContactPanel(id="contact-container", classes="panel")
                yield AgentCardPanel(id="agent-card-container", classes="panel")

            with Vertical(id="right-pane"):
                yield TabbedMessagesPanel(id="messages-container", classes="panel")
                yield InputPanel(id="input-container", classes="panel")
        yield Footer(show_command_palette=False)

    @contextlib.contextmanager
    def _suppressing_auth_events(self) -> Generator[None, None, None]:
        """Suppress auth-field change events during programmatic updates."""
        self._syncing_auth_depth += 1
        try:
            yield
        finally:
            self._syncing_auth_depth -= 1

    @property
    def _is_syncing_auth_panel(self) -> bool:
        """True when auth panel fields are being set programmatically."""
        return self._syncing_auth_depth > 0

    async def on_mount(self) -> None:
        logger.info("TUI application starting")
        self._suspend_target_change_events = True
        self.http_client = build_http_client()
        self.theme = get_theme()

        tui_log_handler = install_tui_log_handler(level=logging.DEBUG)
        tui_log_handler.set_callback(self._on_log_line)

        messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
        messages_panel.load_logs(tui_log_handler.get_lines())

        contact_panel = self.query_one("#contact-container", ContactPanel)
        contact_panel.set_version(__version__)
        self._load_connection_targets()
        self._sync_auth_panel_with_resolved_credentials()

        if self._initial_bearer_token:
            with self._suppressing_auth_events():
                messages_panel.set_bearer_token(self._initial_bearer_token)
            self._manual_auth_override = True

        self._refresh_auth_source_status()

        messages_panel.add_system_message(
            "Welcome! Connect to an agent to start chatting."
        )
        self._suspend_target_change_events = False

    def _load_connection_targets(self) -> None:
        """Load profile and saved URL targets into the contact panel."""
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

        contact_panel = self.query_one("#contact-container", ContactPanel)
        contact_panel.set_connection_targets(
            profile_urls=profile_urls, saved_urls=saved_urls
        )

    def _resolve_connection_credentials(
        self,
        agent_url: str,
        selected_profile_name: str | None,
        manual_credentials: AuthCredentials | None,
        manual_override: bool = False,
    ) -> tuple[AuthCredentials | None, str, str | None]:
        """Resolve credentials for connect/send using a consistent precedence order."""
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

    def _refresh_auth_source_status(self) -> None:
        """Refresh the contact panel auth source indicator."""
        try:
            contact_panel = self.query_one("#contact-container", ContactPanel)
            messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
        except Exception:
            return

        agent_url = contact_panel.get_url()
        if not agent_url:
            contact_panel.set_auth_source_status("none")
            return

        manual_credentials = messages_panel.get_auth_credentials()
        selected_profile_name = contact_panel.get_selected_profile_name()
        _, source_description, _ = self._resolve_connection_credentials(
            agent_url=agent_url,
            selected_profile_name=selected_profile_name,
            manual_credentials=manual_credentials,
            manual_override=self._manual_auth_override,
        )
        contact_panel.set_auth_source_status(source_description)

    def _sync_auth_panel_with_resolved_credentials(self) -> None:
        """Populate auth tab fields from resolved credentials for the current URL."""
        if self._manual_auth_override:
            return

        contact_panel = self.query_one("#contact-container", ContactPanel)
        messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)

        agent_url = contact_panel.get_url()
        if not agent_url:
            messages_panel.set_auth_credentials(None)
            return

        selected_profile_name = contact_panel.get_selected_profile_name()
        resolved_credentials, _, _ = self._resolve_connection_credentials(
            agent_url=agent_url,
            selected_profile_name=selected_profile_name,
            manual_credentials=None,
        )
        with self._suppressing_auth_events():
            messages_panel.set_auth_credentials(resolved_credentials)

    def _handle_connection_target_transition(self) -> None:
        """Apply profile/saved auth when a non-custom target is selected."""
        contact_panel = self.query_one("#contact-container", ContactPanel)
        target_id = contact_panel.get_selected_target_id()
        if target_id == "custom":
            return

        self._manual_auth_override = False
        self._sync_auth_panel_with_resolved_credentials()
        self._refresh_auth_source_status()

    def _on_log_line(self, line: str) -> None:
        """Callback for new log lines."""
        try:
            messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
            messages_panel.add_log(line)
        except Exception:
            pass

    def watch_theme(self, new_theme: str) -> None:
        """Called when the app theme changes."""
        logger.debug("Theme changed to: %s", new_theme)
        save_theme(new_theme)
        agent_card_panel = self.query_one("#agent-card-container", AgentCardPanel)
        agent_card_panel.refresh_theme()

    async def _connect_to_agent(
        self,
        agent_url: str,
        credentials: AuthCredentials | None = None,
    ) -> AgentCard:
        if self.http_client:
            await self.http_client.aclose()

        self.http_client = build_http_client(credentials=credentials)

        logger.info("Connecting to agent at %s", agent_url)
        self._agent_service = A2AService(
            self.http_client,
            agent_url,
            credentials=credentials,
        )
        return await self._agent_service.get_card()

    def _update_ui_for_connected_state(self, agent_card: AgentCard) -> None:
        agent_card_panel = self.query_one("#agent-card-container", AgentCardPanel)
        agent_card_panel.update_card(agent_card)

        messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
        messages_panel.update_message_count()

    @on(Select.Changed, "#connection-target")
    def _handle_connection_target_changed(self) -> None:
        if self._suspend_target_change_events:
            return
        self._handle_connection_target_transition()

    @on(Input.Changed, "#agent-url")
    def _handle_agent_url_changed(self) -> None:
        contact_panel = self.query_one("#contact-container", ContactPanel)
        target_id = contact_panel.get_selected_target_id()
        if target_id != "custom":
            self._handle_connection_target_transition()
            return

        self._sync_auth_panel_with_resolved_credentials()
        self._refresh_auth_source_status()

    @on(RadioSet.Changed, "#auth-type-selector")
    @on(
        Input.Changed,
        "#api-key-input, #api-key-header-input, #bearer-token-input, "
        "#custom-headers-input, #mtls-cert-input, #mtls-key-input, #mtls-ca-input",
    )
    def _handle_auth_field_changed(self) -> None:
        """Track manual edits to any auth panel field."""
        if not self._is_syncing_auth_panel:
            self._manual_auth_override = True
        self._refresh_auth_source_status()

    @on(Button.Pressed, "#connect-btn")
    async def handle_connect_button(self) -> None:
        contact_panel = self.query_one("#contact-container", ContactPanel)
        agent_url = contact_panel.get_url()

        if not agent_url:
            logger.warning("Connect attempted with empty URL")
            messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
            messages_panel.add_system_message("Please enter an agent URL")
            return

        messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
        messages_panel.add_system_message(f"Connecting to {agent_url}...")

        try:
            selected_profile_name = contact_panel.get_selected_profile_name()
            manual_credentials = (
                messages_panel.get_auth_credentials()
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
            contact_panel.set_auth_source_status(source_description)
            if warning:
                messages_panel.add_system_message(warning)

            agent_card = await self._connect_to_agent(agent_url, credentials)

            self.current_agent_card = agent_card
            self.current_agent_url = agent_url
            self.current_context_id = str(uuid.uuid4())

            logger.info("Successfully connected to %s", agent_card.name)

            self._update_ui_for_connected_state(agent_card)
            messages_panel.add_system_message(f"Connected to {agent_card.name}")

            agent_card_panel = self.query_one("#agent-card-container", AgentCardPanel)
            agent_card_panel.focus()

        except Exception as error:
            logger.error("Connection failed: %s", error, exc_info=True)
            messages_panel.add_system_message(f"Connection failed: {error!s}")
            agent_card_panel = self.query_one("#agent-card-container", AgentCardPanel)
            agent_card_panel.update_card(None)

    @on(Input.Submitted, "#message-input")
    def handle_message_submit(self) -> None:
        if self.current_agent_url:
            self._send_message()
        else:
            messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
            messages_panel.add_system_message("Not connected to an agent")

    @on(Button.Pressed, "#send-btn")
    def handle_send_button(self) -> None:
        if self.current_agent_url:
            self._send_message()
        else:
            messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
            messages_panel.add_system_message("Not connected to an agent")

    @work(exclusive=True)
    async def _send_message(self) -> None:
        if not self.current_agent_url or not self._agent_service:
            logger.warning("Attempted to send message without connection")
            messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
            messages_panel.add_system_message("Not connected to an agent")
            return

        input_panel = self.query_one("#input-container", InputPanel)
        message_text = input_panel.get_message()

        if not message_text:
            return

        messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
        messages_panel.add_message("user", message_text)

        try:
            logger.info("Sending message: %s", message_text[:50])

            contact_panel = self.query_one("#contact-container", ContactPanel)
            selected_profile_name = contact_panel.get_selected_profile_name()
            manual_credentials = (
                messages_panel.get_auth_credentials()
                if self._manual_auth_override
                else None
            )
            credentials, source_description, _ = self._resolve_connection_credentials(
                agent_url=self.current_agent_url,
                selected_profile_name=selected_profile_name,
                manual_credentials=manual_credentials,
                manual_override=self._manual_auth_override,
            )
            contact_panel.set_auth_source_status(source_description)

            if credentials:
                self._agent_service.set_credentials(credentials)
            else:
                self._agent_service.clear_credentials()

            send_result = await self._agent_service.send(
                message_text,
                context_id=self.current_context_id,
            )

            if send_result.context_id:
                self.current_context_id = send_result.context_id

            logger.info(
                "Response received - task_id=%s, state=%s, has_text=%s, has_task=%s, has_message=%s",
                send_result.task_id,
                send_result.state,
                bool(send_result.text),
                send_result.task is not None,
                send_result.message is not None,
            )
            if send_result.task:
                logger.debug("Raw response: %s", send_result.task.model_dump())
            elif send_result.message:
                logger.debug("Raw response: %s", send_result.message.model_dump())

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
            logger.error("Error sending message: %s", error, exc_info=True)
            messages_panel.add_system_message(f"Error: {error!s}")

    def action_toggle_maximize(self) -> None:
        """Toggle maximize for the focused panel."""
        if self._is_maximized:
            self.screen.minimize()
            self._is_maximized = False
            return

        focused = self.focused
        if focused is None:
            return

        for panel in (
            self.query_one("#messages-container", TabbedMessagesPanel),
            self.query_one("#agent-card-container", AgentCardPanel),
        ):
            if focused is panel or panel in focused.ancestors:
                self.screen.maximize(panel)
                self._is_maximized = True
                return

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Filter out maximize/minimize commands from the command palette."""
        for command in super().get_system_commands(screen):
            if command.title.lower() in ("maximize", "minimize"):
                continue
            yield command

    async def on_unmount(self) -> None:
        logger.info("Shutting down TUI application")
        if self.http_client:
            await self.http_client.aclose()


def main() -> None:
    """Entry point for the TUI application."""
    application = HandlerTUI()
    application.run()


if __name__ == "__main__":
    main()
