"""Contact panel component for managing agent connections."""

import webbrowser
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Input, Link, Static, TabbedContent, TabPane, Tabs

from a2a_handler.common import get_logger

logger = get_logger(__name__)

REPORT_BUG_URL = "https://github.com/alDuncanson/Handler/issues"
SPONSOR_URL = "https://github.com/sponsors/alDuncanson"
DISCUSS_URL = "https://github.com/alDuncanson/Handler/discussions"


class ContactPanel(Container):
    """Contact panel for connecting to an agent endpoint."""

    ALLOW_MAXIMIZE = False

    BINDINGS = [
        Binding("h", "previous_tab", "← Tab", show=True, key_display="h/←"),
        Binding("l", "next_tab", "→ Tab", show=True, key_display="l/→"),
        Binding("left", "previous_tab", "Previous Tab", show=False),
        Binding("right", "next_tab", "Next Tab", show=False),
        Binding("enter", "focus_input", "Edit URL", show=True),
        Binding("b", "open_bug_report", "Bug", show=True),
        Binding("s", "open_sponsor", "Sponsor", show=True),
        Binding("d", "open_discuss", "Discuss", show=True),
    ]

    can_focus = True

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Show/hide actions based on active tab context."""
        is_help = self._is_help_tab_active()
        if action in ("open_bug_report", "open_sponsor", "open_discuss"):
            return is_help
        if action == "focus_input":
            return not is_help
        return True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._version: str = "0.0.0"

    def compose(self) -> ComposeResult:
        with TabbedContent(id="contact-tabs"):
            with TabPane("Server", id="server-tab"):
                yield Vertical(
                    Horizontal(
                        Input(
                            placeholder="http://localhost:8000",
                            value="http://localhost:8000",
                            id="agent-url",
                        ),
                        Button("CONNECT", id="connect-btn"),
                        id="url-row",
                    ),
                    id="server-content",
                )
            with TabPane("Help", id="help-tab"):
                yield Vertical(
                    Static(id="version-info"),
                    Static("[dim]b[/dim] Report a bug:", classes="link-label"),
                    Link(REPORT_BUG_URL, url=REPORT_BUG_URL, id="report-bug-link"),
                    Static("[dim]s[/dim] Sponsor or donate:", classes="link-label"),
                    Link(SPONSOR_URL, url=SPONSOR_URL, id="sponsor-link"),
                    Static("[dim]d[/dim] Start a discussion:", classes="link-label"),
                    Link(DISCUSS_URL, url=DISCUSS_URL, id="discuss-link"),
                    id="help-content",
                )

    def on_mount(self) -> None:
        for widget in self.query("TabbedContent, Tabs, Tab, TabPane"):
            widget.can_focus = False
        self.query_one("#agent-url", Input).can_focus = False
        self.query_one("#connect-btn", Button).can_focus = False
        for link in self.query(Link):
            link.can_focus = False
        self._update_version_display()
        logger.debug("Contact panel mounted")

    @on(TabbedContent.TabActivated)
    def _on_tab_activated(self) -> None:
        """Refresh bindings when switching tabs."""
        self.refresh_bindings()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle enter key in the URL input to connect."""
        connect_btn = self.query_one("#connect-btn", Button)
        self.post_message(Button.Pressed(connect_btn))

    def action_focus_input(self) -> None:
        """Focus the URL input field."""
        url_input = self.query_one("#agent-url", Input)
        url_input.can_focus = True
        url_input.focus()

    def on_descendant_blur(self) -> None:
        """Disable focus on input when it loses focus."""
        url_input = self.query_one("#agent-url", Input)
        url_input.can_focus = False

    def action_previous_tab(self) -> None:
        """Switch to the previous tab."""
        try:
            tabs_widget = self.query_one("#contact-tabs Tabs", Tabs)
            tabs_widget.action_previous_tab()
        except Exception:
            pass

    def action_next_tab(self) -> None:
        """Switch to the next tab."""
        try:
            tabs_widget = self.query_one("#contact-tabs Tabs", Tabs)
            tabs_widget.action_next_tab()
        except Exception:
            pass

    def _is_help_tab_active(self) -> bool:
        """Check if the Help tab is currently active."""
        try:
            tabs = self.query_one("#contact-tabs", TabbedContent)
            return tabs.active == "help-tab"
        except Exception:
            return False

    def action_open_bug_report(self) -> None:
        """Open the bug report URL."""
        if not self._is_help_tab_active():
            return
        webbrowser.open(REPORT_BUG_URL)

    def action_open_sponsor(self) -> None:
        """Open the sponsor URL."""
        if not self._is_help_tab_active():
            return
        webbrowser.open(SPONSOR_URL)

    def action_open_discuss(self) -> None:
        """Open the discuss URL."""
        if not self._is_help_tab_active():
            return
        webbrowser.open(DISCUSS_URL)

    def set_version(self, version: str) -> None:
        """Set the application version."""
        self._version = version
        self._update_version_display()

    def _update_version_display(self) -> None:
        """Update the version info display."""
        try:
            version_widget = self.query_one("#version-info", Static)
            version_widget.update(f"Handler v{self._version}")
        except Exception:
            pass

    def get_url(self) -> str:
        """Get the current agent URL from the input field."""
        url_input = self.query_one("#agent-url", Input)
        return url_input.value.strip()

    def set_url(self, url: str) -> None:
        """Set the agent URL input field."""
        url_input = self.query_one("#agent-url", Input)
        url_input.value = url
