"""Main TUI application for Handler.

Provides the Textual-based terminal interface for agent interaction.
"""

import logging
import uuid
from collections.abc import Iterable
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
from textual.widgets import Button, Footer, Input

from a2a_handler.auth import AuthCredentials
from a2a_handler.common import get_theme, install_tui_log_handler, save_theme
from a2a_handler.service import A2AService
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
) -> httpx.AsyncClient:
    """Build an HTTP client with the specified timeout."""
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

    def compose(self) -> ComposeResult:
        with Container(id="root-container"):
            with Vertical(id="left-pane"):
                yield ContactPanel(id="contact-container", classes="panel")
                yield AgentCardPanel(id="agent-card-container", classes="panel")

            with Vertical(id="right-pane"):
                yield TabbedMessagesPanel(id="messages-container", classes="panel")
                yield InputPanel(id="input-container", classes="panel")
        yield Footer(show_command_palette=False)

    async def on_mount(self) -> None:
        logger.info("TUI application starting")
        self.http_client = build_http_client()
        self.theme = get_theme()

        tui_log_handler = install_tui_log_handler(level=logging.DEBUG)
        tui_log_handler.set_callback(self._on_log_line)

        messages_panel = self.query_one("#messages-container", TabbedMessagesPanel)
        messages_panel.load_logs(tui_log_handler.get_lines())
        if self._initial_bearer_token:
            messages_panel.set_bearer_token(self._initial_bearer_token)

        contact_panel = self.query_one("#contact-container", ContactPanel)
        contact_panel.set_version(__version__)

        messages_panel.add_system_message(
            "Welcome! Connect to an agent to start chatting."
        )

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
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")

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
            credentials = messages_panel.get_auth_credentials()
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

            credentials = messages_panel.get_auth_credentials()
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
