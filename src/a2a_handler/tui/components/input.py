"""Input panel component for composing and sending messages."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Input, LoadingIndicator, Static

from a2a_handler.common import get_logger

logger = get_logger(__name__)


class InputPanel(Container):
    """Panel for message input."""

    ALLOW_MAXIMIZE = False
    DEFAULT_PLACEHOLDER = "Type your message..."
    DISCONNECTED_PLACEHOLDER = "Connect to an agent to start chatting."
    WAITING_PLACEHOLDER = "Waiting for agent response..."

    def compose(self) -> ComposeResult:
        with Horizontal(id="input-row"):
            yield Input(placeholder="Type your message...", id="message-input")
            yield LoadingIndicator(id="send-loading", classes="hidden")
            yield Static(
                "Waiting for agent...", id="send-loading-label", classes="hidden"
            )
            yield Button("SEND", id="send-btn")

    def on_mount(self) -> None:
        self.query_one("#send-btn", Button).can_focus = False
        logger.debug("Input panel mounted")

    def get_message(self) -> str:
        """Get and clear the current message input."""
        message_input = self.query_one("#message-input", Input)
        message_text = message_input.value.strip()
        message_input.value = ""
        return message_text

    def focus_input(self) -> None:
        """Focus the message input field."""
        self.query_one("#message-input", Input).focus()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable message composition based on connection state."""
        message_input = self.query_one("#message-input", Input)
        send_button = self.query_one("#send-btn", Button)
        loading = self.query_one("#send-loading", LoadingIndicator)
        label = self.query_one("#send-loading-label", Static)
        message_input.disabled = not enabled
        send_button.disabled = not enabled
        if enabled:
            message_input.placeholder = self.DEFAULT_PLACEHOLDER
            return
        message_input.value = ""
        message_input.placeholder = self.DISCONNECTED_PLACEHOLDER
        loading.add_class("hidden")
        label.add_class("hidden")

    def set_waiting(self, waiting: bool) -> None:
        """Show or hide the in-flight request indicator."""
        message_input = self.query_one("#message-input", Input)
        send_button = self.query_one("#send-btn", Button)
        loading = self.query_one("#send-loading", LoadingIndicator)
        label = self.query_one("#send-loading-label", Static)

        message_input.disabled = waiting
        send_button.disabled = waiting
        if waiting:
            message_input.placeholder = self.WAITING_PLACEHOLDER
            loading.remove_class("hidden")
            label.remove_class("hidden")
            return

        message_input.placeholder = self.DEFAULT_PLACEHOLDER
        loading.add_class("hidden")
        label.add_class("hidden")
