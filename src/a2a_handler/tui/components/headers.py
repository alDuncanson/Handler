"""Headers panel component for configuring custom request headers."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label

from a2a_handler.auth import parse_header_string
from a2a_handler.common import get_logger

logger = get_logger(__name__)


class HeadersPanel(Vertical):
    """Panel for configuring custom headers sent with every request."""

    can_focus = False

    def compose(self) -> ComposeResult:
        yield Label("Custom Headers (semicolon-separated)")
        yield Input(
            placeholder="x-user-id: me@mydomain.com; x-org: acme",
            id="custom-headers-input",
        )

    def get_headers(self) -> dict[str, str] | None:
        """Parse the custom-headers field into a header dictionary."""
        raw = self.query_one("#custom-headers-input", Input).value.strip()
        if not raw:
            return None

        headers: dict[str, str] = {}
        for line in raw.split(";"):
            line = line.strip()
            if not line:
                continue
            try:
                name, value = parse_header_string(line)
                headers[name] = value
            except ValueError:
                logger.warning("Skipping invalid custom header: %s", line)

        return headers or None

    def set_headers(self, headers: dict[str, str] | None) -> None:
        """Preconfigure custom headers from a dictionary."""
        headers_input = self.query_one("#custom-headers-input", Input)
        if not headers:
            headers_input.value = ""
            return
        headers_input.value = "; ".join(
            f"{name}: {value}" for name, value in headers.items()
        )

    def clear(self) -> None:
        """Reset custom headers."""
        self.query_one("#custom-headers-input", Input).value = ""
