"""Agent card panel component for displaying agent metadata and capabilities."""

import json
from typing import Any

from a2a.types import AgentCard
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.widgets import Static

from a2a_handler.common import get_logger
from a2a_handler.service import to_json_dict

logger = get_logger(__name__)

TEXTUAL_TO_SYNTAX_THEME_MAP: dict[str, str] = {
    "gruvbox": "gruvbox-dark",
    "nord": "nord",
    "textual-light": "default",
    "solarized-light": "solarized-light",
    "dracula": "dracula",
}


class AgentCardPanel(Container):
    """Panel displaying agent card information with tabs."""

    BINDINGS = [
        Binding(
            "j", "scroll_down", "\u2193 Scroll", show=False, key_display="j/\u2193"
        ),
        Binding("k", "scroll_up", "\u2191 Scroll", show=False, key_display="k/\u2191"),
        Binding("down", "scroll_down", "Scroll Down", show=False),
        Binding("up", "scroll_up", "Scroll Up", show=False),
        Binding("ctrl+d", "scroll_half_down", "\u00bd Page \u2193", show=False),
        Binding("ctrl+u", "scroll_half_up", "\u00bd Page \u2191", show=False),
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
        self._current_raw_card: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Connect to an A2A server"),
            id="placeholder",
        )
        yield VerticalScroll(
            Static("", id="agent-raw"),
            id="raw-scroll",
        )

    def on_mount(self) -> None:
        for widget in self.query("VerticalScroll"):
            widget.can_focus = False
        self._show_placeholder()
        logger.debug("Agent card panel mounted")

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

    def _card_json(self) -> str:
        """Render the card to display, preferring the JSON the server served.

        Falling back to the typed model would silently hide any field the v1.0
        ``AgentCard`` has no home for (the v0.3 top-level ``protocolVersion``,
        ``url`` and ``preferredTransport``), which is exactly the detail someone
        debugging a card came here to see.
        """
        if self._current_raw_card is not None:
            return json.dumps(self._current_raw_card, indent=2, default=str)
        return json.dumps(to_json_dict(self._current_agent_card), indent=2, default=str)

    def update_card(
        self,
        agent_card: AgentCard | None,
        raw_card: dict[str, Any] | None = None,
    ) -> None:
        """Update the displayed agent card.

        Args:
            agent_card: The parsed card, or None to clear the panel
            raw_card: The card JSON as served, displayed in preference to the
                parsed model because parsing is lossy
        """
        self._current_agent_card = agent_card
        self._current_raw_card = raw_card if agent_card is not None else None
        self.refresh_bindings()

        raw_view_widget = self.query_one("#agent-raw", Static)

        if agent_card is None:
            logger.debug("Clearing agent card display")
            raw_view_widget.update("")
            self._show_placeholder()
        else:
            logger.info("Displaying agent card for: %s", agent_card.name)
            json_content = self._card_json()
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
        json_content = self._card_json()
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
