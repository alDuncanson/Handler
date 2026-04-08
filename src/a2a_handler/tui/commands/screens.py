"""Small prompt screens used by command palette actions."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class TextPromptScreen(ModalScreen[str | None]):
    """Prompt for a single line of text."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        value: str = "",
        placeholder: str = "",
        confirm_label: str = "Save",
    ) -> None:
        super().__init__()
        self._title = title
        self._subtitle = subtitle
        self._value = value
        self._placeholder = placeholder
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="command-dialog"):
            yield Static(self._title, id="command-dialog-title")
            yield Static(self._subtitle, id="command-dialog-subtitle")
            yield Input(
                value=self._value,
                placeholder=self._placeholder,
                id="command-dialog-input",
                select_on_focus=True,
            )
            with Horizontal(id="command-dialog-buttons"):
                yield Button("Cancel", id="command-dialog-cancel")
                yield Button(self._confirm_label, id="command-dialog-confirm")

    def on_mount(self) -> None:
        self.query_one("#command-dialog-input", Input).focus()

    @on(Button.Pressed, "#command-dialog-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#command-dialog-confirm")
    def _confirm(self) -> None:
        value = self.query_one("#command-dialog-input", Input).value.strip()
        self.dismiss(value or None)

    @on(Input.Submitted, "#command-dialog-input")
    def _submit(self) -> None:
        self._confirm()


class ConfirmScreen(ModalScreen[bool]):
    """Simple yes/no confirmation screen."""

    def __init__(
        self, title: str, subtitle: str, *, confirm_label: str = "Confirm"
    ) -> None:
        super().__init__()
        self._title = title
        self._subtitle = subtitle
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="command-dialog"):
            yield Static(self._title, id="command-dialog-title")
            yield Static(self._subtitle, id="command-dialog-subtitle")
            with Horizontal(id="command-dialog-buttons"):
                yield Button("Cancel", id="command-dialog-cancel")
                yield Button(self._confirm_label, id="command-dialog-confirm")

    @on(Button.Pressed, "#command-dialog-cancel")
    def _cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#command-dialog-confirm")
    def _confirm(self) -> None:
        self.dismiss(True)
