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
    INPUT_REQUIRED_PLACEHOLDER = "The agent is waiting for your reply..."

    def compose(self) -> ComposeResult:
        with Horizontal(id="input-row"):
            yield Input(placeholder="Type your message...", id="message-input")
            yield LoadingIndicator(id="send-loading", classes="hidden")
            yield Static(
                "Waiting for agent...", id="send-loading-label", classes="hidden"
            )
            yield Button("STOP", id="cancel-btn", variant="error", classes="hidden")
            yield Button("SEND", id="send-btn")

    def on_mount(self) -> None:
        self.query_one("#send-btn", Button).can_focus = False
        self.query_one("#cancel-btn", Button).can_focus = False
        logger.debug("Input panel mounted")

    def set_status(self, text: str) -> None:
        """Update the in-flight label with the agent's current state."""
        self.query_one("#send-loading-label", Static).update(text)

    def prompt_for_reply(self) -> None:
        """Signal that the agent asked a question and is waiting on the user."""
        message_input = self.query_one("#message-input", Input)
        message_input.placeholder = self.INPUT_REQUIRED_PLACEHOLDER

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
        self.query_one("#cancel-btn", Button).add_class("hidden")

    def set_waiting(self, waiting: bool, *, cancellable: bool = False) -> None:
        """Show or hide the in-flight request indicator.

        ``cancellable`` reveals the stop control, which is only meaningful for
        a streaming turn the client can actually interrupt.
        """
        message_input = self.query_one("#message-input", Input)
        send_button = self.query_one("#send-btn", Button)
        loading = self.query_one("#send-loading", LoadingIndicator)
        label = self.query_one("#send-loading-label", Static)
        cancel_button = self.query_one("#cancel-btn", Button)

        message_input.disabled = waiting
        send_button.disabled = waiting
        if waiting:
            message_input.placeholder = self.WAITING_PLACEHOLDER
            label.update("Waiting for agent...")
            loading.remove_class("hidden")
            label.remove_class("hidden")
            cancel_button.set_class(not cancellable, "hidden")
            cancel_button.disabled = not cancellable
            return

        message_input.placeholder = self.DEFAULT_PLACEHOLDER
        loading.add_class("hidden")
        label.add_class("hidden")
        cancel_button.add_class("hidden")
