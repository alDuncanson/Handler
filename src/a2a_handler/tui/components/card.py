"""Agent card panel component for displaying agent metadata and capabilities."""

import json
from typing import Any

from a2a.types import AgentCard
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static

from a2a_handler.auth import AuthType
from a2a_handler.common import get_logger
from a2a_handler.session import get_session_store

logger = get_logger(__name__)

TEXTUAL_TO_SYNTAX_THEME_MAP: dict[str, str] = {
    "gruvbox": "gruvbox-dark",
    "nord": "nord",
    "textual-light": "default",
    "solarized-light": "solarized-light",
    "dracula": "dracula",
}

AUTH_TYPE_LABELS: dict[AuthType, str] = {
    AuthType.BEARER: "Bearer",
    AuthType.API_KEY: "API Key",
    AuthType.MTLS: "mTLS",
}


class AgentCardPanel(Container):
    """Panel displaying agent card information with tabs."""

    class AgentSelected(Message):
        def __init__(self, agent_url: str) -> None:
            super().__init__()
            self.agent_url = agent_url

    BINDINGS = [
        Binding("j", "scroll_down", "\u2193 Scroll", show=True, key_display="j/\u2193"),
        Binding("k", "scroll_up", "\u2191 Scroll", show=True, key_display="k/\u2191"),
        Binding("down", "scroll_down", "Scroll Down", show=False),
        Binding("up", "scroll_up", "Scroll Up", show=False),
        Binding("ctrl+d", "scroll_half_down", "\u00bd Page \u2193", show=True),
        Binding("ctrl+u", "scroll_half_up", "\u00bd Page \u2191", show=True),
    ]

    can_focus = True

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Hide scroll actions when no agent card is loaded."""
        if action in ("scroll_down", "scroll_up", "scroll_half_down", "scroll_half_up"):
            return self._current_agent_card is not None
        return True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current_agent_card: AgentCard | None = None
        self._button_url_map: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Vertical(id="placeholder")
        yield VerticalScroll(
            Static("", id="agent-raw"),
            id="raw-scroll",
        )

    def on_mount(self) -> None:
        for widget in self.query("VerticalScroll"):
            widget.can_focus = False
        self._populate_saved_agents()
        self._show_placeholder()
        logger.debug("Agent card panel mounted")

    def _populate_saved_agents(self) -> None:
        placeholder = self.query_one("#placeholder", Vertical)
        placeholder.remove_children()
        self._button_url_map.clear()

        store = get_session_store()
        sessions = store.list_all()
        agents_with_creds = [s for s in sessions if s.credentials is not None]

        if not agents_with_creds:
            placeholder.mount(Static("Connect to an A2A server"))
            return

        placeholder.mount(Static("Saved Agents", classes="saved-agents-title"))
        for idx, session in enumerate(agents_with_creds):
            auth_label = ""
            if session.credentials:
                auth_label = AUTH_TYPE_LABELS.get(session.credentials.auth_type, "")
                if session.credentials.custom_headers:
                    header_names = ", ".join(session.credentials.custom_headers.keys())
                    if auth_label:
                        auth_label = f"{auth_label} + {header_names}"
                    else:
                        auth_label = header_names

            label = session.agent_url
            if auth_label:
                label = f"{session.agent_url}  [{auth_label}]"

            button_id = f"saved-agent-{idx}"
            self._button_url_map[button_id] = session.agent_url
            placeholder.mount(Button(label, id=button_id, classes="saved-agent-btn"))

    def _on_button_pressed(self, event: Button.Pressed) -> None:
        if "saved-agent-btn" not in event.button.classes:
            return
        agent_url = self._button_url_map.get(event.button.id or "")
        if agent_url:
            self.post_message(self.AgentSelected(agent_url))

    def _show_placeholder(self) -> None:
        """Show the hatch placeholder, hide the raw scroll content."""
        placeholder = self.query_one("#placeholder", Vertical)
        raw_scroll = self.query_one("#raw-scroll", VerticalScroll)
        placeholder.display = True
        raw_scroll.display = False

    def _show_content(self) -> None:
        """Show the raw scroll content, hide the placeholder."""
        placeholder = self.query_one("#placeholder", Vertical)
        raw_scroll = self.query_one("#raw-scroll", VerticalScroll)
        placeholder.display = False
        raw_scroll.display = True

    def _get_syntax_theme_for_current_app_theme(self) -> str | None:
        """Get the Rich Syntax theme name for the current app theme."""
        current_theme = self.app.theme or ""
        return TEXTUAL_TO_SYNTAX_THEME_MAP.get(current_theme)

    def update_card(self, agent_card: AgentCard | None) -> None:
        """Update the displayed agent card."""
        self._current_agent_card = agent_card
        self.refresh_bindings()

        raw_view_widget = self.query_one("#agent-raw", Static)

        if agent_card is None:
            logger.debug("Clearing agent card display")
            raw_view_widget.update("")
            self._populate_saved_agents()
            self._show_placeholder()
        else:
            logger.info("Displaying agent card for: %s", agent_card.name)
            json_content = json.dumps(agent_card.model_dump(), indent=2, default=str)
            syntax_theme = self._get_syntax_theme_for_current_app_theme()
            if syntax_theme:
                raw_view_widget.update(Syntax(json_content, "json", theme=syntax_theme))
            else:
                raw_view_widget.update(json_content)
            self._show_content()

    def refresh_theme(self) -> None:
        """Refresh the raw view syntax highlighting for theme changes."""
        if self._current_agent_card is None:
            return

        logger.debug("Refreshing syntax theme for agent card raw view")
        json_content = json.dumps(
            self._current_agent_card.model_dump(), indent=2, default=str
        )
        syntax_theme = self._get_syntax_theme_for_current_app_theme()
        raw_widget = self.query_one("#agent-raw", Static)
        if syntax_theme:
            raw_widget.update(Syntax(json_content, "json", theme=syntax_theme))
        else:
            raw_widget.update(json_content)

    def action_scroll_down(self) -> None:
        """Scroll down in the scroll container."""
        scroll_container = self.query_one("#raw-scroll", VerticalScroll)
        scroll_container.scroll_down()

    def action_scroll_up(self) -> None:
        """Scroll up in the scroll container."""
        scroll_container = self.query_one("#raw-scroll", VerticalScroll)
        scroll_container.scroll_up()

    def action_scroll_half_down(self) -> None:
        """Scroll down half a page."""
        scroll_container = self.query_one("#raw-scroll", VerticalScroll)
        scroll_container.scroll_relative(y=scroll_container.size.height // 2)

    def action_scroll_half_up(self) -> None:
        """Scroll up half a page."""
        scroll_container = self.query_one("#raw-scroll", VerticalScroll)
        scroll_container.scroll_relative(y=-(scroll_container.size.height // 2))
