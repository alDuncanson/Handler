"""Contact panel component for managing agent connections."""

from dataclasses import dataclass
import webbrowser
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Button,
    Input,
    Link,
    Select,
    Static,
    TabbedContent,
    TabPane,
    Tabs,
)

from a2a_handler.common import get_logger

logger = get_logger(__name__)

REPORT_BUG_URL = "https://github.com/alDuncanson/Handler/issues"
SPONSOR_URL = "https://github.com/sponsors/alDuncanson"
DISCUSS_URL = "https://github.com/alDuncanson/Handler/discussions"
CUSTOM_TARGET_ID = "custom"


@dataclass(frozen=True, slots=True)
class ConnectionTarget:
    """A selectable connection target for the server panel."""

    target_id: str
    label: str
    agent_url: str
    profile_name: str | None = None


class ContactPanel(Container):
    """Contact panel for connecting to an agent endpoint."""

    ALLOW_MAXIMIZE = False

    BINDINGS = [
        Binding("h", "previous_tab", "← Tab", show=True, key_display="h/←"),
        Binding("l", "next_tab", "→ Tab", show=True, key_display="l/→"),
        Binding("left", "previous_tab", "Previous Tab", show=False),
        Binding("right", "next_tab", "Next Tab", show=False),
        Binding("enter", "focus_input", "Edit URL", show=True),
        Binding("p", "focus_selector", "Profiles", show=True),
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
        if action in ("focus_input", "focus_selector"):
            return not is_help
        return True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._version: str = "0.0.0"
        self._connection_targets: dict[str, ConnectionTarget] = {}
        self._selected_target_id: str = CUSTOM_TARGET_ID

    def compose(self) -> ComposeResult:
        with TabbedContent(id="contact-tabs"):
            with TabPane("Server", id="server-tab"):
                yield Vertical(
                    Select(
                        [("Custom URL", CUSTOM_TARGET_ID)],
                        allow_blank=False,
                        value=CUSTOM_TARGET_ID,
                        id="connection-target",
                    ),
                    Horizontal(
                        Input(
                            placeholder="http://localhost:8000",
                            value="http://localhost:8000",
                            id="agent-url",
                        ),
                        Button("CONNECT", id="connect-btn"),
                        id="url-row",
                    ),
                    Static("Auth source: none", id="auth-source-status"),
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
        self.query_one("#connection-target", Select).can_focus = False
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

    @on(Select.Changed, "#connection-target")
    def _on_connection_target_changed(self, event: Select.Changed) -> None:
        """Apply URL changes when the selected profile/saved target changes."""
        if event.value == Select.BLANK:
            return

        target_id = str(event.value)
        self._selected_target_id = target_id
        target = self._connection_targets.get(target_id)
        if target:
            self.query_one("#agent-url", Input).value = target.agent_url
            logger.debug("Selected connection target: %s", target.label)

    @on(Input.Changed, "#agent-url")
    def _on_agent_url_changed(self, event: Input.Changed) -> None:
        """Switch to custom mode when the URL is manually edited."""
        selected = self._connection_targets.get(self._selected_target_id)
        if selected and selected.agent_url == event.value.strip():
            return

        if self._selected_target_id == CUSTOM_TARGET_ID:
            return

        self._selected_target_id = CUSTOM_TARGET_ID
        selector = self.query_one("#connection-target", Select)
        selector.value = CUSTOM_TARGET_ID

    def action_focus_input(self) -> None:
        """Focus the URL input field."""
        url_input = self.query_one("#agent-url", Input)
        url_input.can_focus = True
        url_input.focus()

    def action_focus_selector(self) -> None:
        """Focus the profile/URL selector."""
        selector = self.query_one("#connection-target", Select)
        selector.can_focus = True
        selector.focus()

    def on_descendant_blur(self) -> None:
        """Disable focus on input when it loses focus."""
        selector = self.query_one("#connection-target", Select)
        selector.can_focus = False
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

    def set_connection_targets(
        self,
        profile_urls: dict[str, str],
        saved_urls: list[str],
    ) -> None:
        """Populate selector options with profiles and saved URLs."""
        targets: dict[str, ConnectionTarget] = {
            CUSTOM_TARGET_ID: ConnectionTarget(
                target_id=CUSTOM_TARGET_ID,
                label="Custom URL",
                agent_url="",
                profile_name=None,
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

        known_profile_urls = {url for url in profile_urls.values()}
        for url in saved_urls:
            if url in known_profile_urls:
                continue
            target_id = f"saved:{url}"
            label = f"Saved: {url}"
            targets[target_id] = ConnectionTarget(
                target_id=target_id,
                label=label,
                agent_url=url,
                profile_name=None,
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
        """Update the auth source status shown under the server controls."""
        status = self.query_one("#auth-source-status", Static)
        status.update(f"Auth source: {source_description}")

    def get_url(self) -> str:
        """Get the current agent URL from the input field."""
        url_input = self.query_one("#agent-url", Input)
        return url_input.value.strip()

    def get_selected_profile_name(self) -> str | None:
        """Get profile name for the current selector value, if any."""
        selected = self._connection_targets.get(self._selected_target_id)
        if selected is None:
            return None
        return selected.profile_name

    def get_selected_target_id(self) -> str:
        """Get the selected connection target identifier."""
        return self._selected_target_id
