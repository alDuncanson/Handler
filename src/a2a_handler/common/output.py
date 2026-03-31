"""Simple output formatting system for CLI.

Provides plain text and structured JSON/NDJSON output.

Display methods (header, field, blank, etc.) only produce output in text mode.
In structured modes (json/ndjson), commands emit domain data via json().
"""

from __future__ import annotations

import json as json_module
import sys
from typing import Any, Literal

TERMINAL_STATES = {"completed", "failed", "canceled", "rejected"}
SUCCESS_STATES = {"completed"}
ERROR_STATES = {"failed", "rejected"}
WARNING_STATES = {"canceled"}

OutputFormat = Literal["text", "json", "ndjson"]

_DEFAULT_OUTPUT_FORMAT: OutputFormat = "text"
_DEFAULT_QUIET = False


def configure_output(output_format: OutputFormat = "text", quiet: bool = False) -> None:
    """Configure default output behavior for CLI commands."""
    global _DEFAULT_OUTPUT_FORMAT, _DEFAULT_QUIET
    _DEFAULT_OUTPUT_FORMAT = output_format
    _DEFAULT_QUIET = quiet


class Output:
    """Manages console output.

    Text-mode display methods (header, field, blank, etc.) are no-ops in
    structured modes.  Commands emit domain data via json() which works
    across all modes.
    """

    def __init__(
        self,
        output_format: OutputFormat | None = None,
        quiet: bool | None = None,
    ) -> None:
        self._output_format: OutputFormat = output_format or _DEFAULT_OUTPUT_FORMAT
        self._quiet = _DEFAULT_QUIET if quiet is None else quiet

    @property
    def is_structured(self) -> bool:
        """Return True when output mode is json or ndjson."""
        return self._output_format != "text"

    def _print(self, text: str) -> None:
        """Print text to stdout."""
        print(text)

    def _print_err(self, text: str) -> None:
        """Print text to stderr."""
        print(text, file=sys.stderr)

    def _emit_text(self, text: str, force: bool = False) -> None:
        """Print plain text output with quiet-mode handling."""
        if self._quiet and not force:
            return
        self._print(text)

    # ------------------------------------------------------------------
    # Domain data — works in ALL modes
    # ------------------------------------------------------------------

    def json(self, data: Any) -> None:
        """Emit domain data.  This is the primary output method for
        structured modes and also works in text mode (pretty-printed)."""
        if self._quiet:
            return
        if self._output_format == "ndjson":
            self._print(json_module.dumps(data, default=str))
        elif self._output_format == "json":
            self._print(json_module.dumps(data, indent=2, default=str))
        else:
            self._print(json_module.dumps(data, indent=2, default=str))

    def error_obj(
        self,
        code: str,
        message: str,
        details: Any | None = None,
        suggestion: str | None = None,
    ) -> None:
        """Emit a standardized error envelope (always emitted, ignores quiet).

        In text mode prints the message to stderr.
        In structured modes emits a stable error object to stdout.
        """
        if self._output_format == "text":
            self._print_err(message)
            return

        payload: dict[str, Any] = {
            "type": "error",
            "code": code,
            "message": message,
        }
        if details is not None:
            payload["details"] = details
        if suggestion:
            payload["suggestion"] = suggestion
        self._print(json_module.dumps(payload, default=str)
                     if self._output_format == "ndjson"
                     else json_module.dumps(payload, indent=2, default=str))

    # ------------------------------------------------------------------
    # Text-only display helpers — no-ops in structured modes
    # ------------------------------------------------------------------

    def line(self, text: str) -> None:
        """Print a line of text (text mode only)."""
        if self.is_structured:
            return
        self._emit_text(text)

    def field(self, name: str, value: Any) -> None:
        """Print a field as 'Name: value' (text mode only)."""
        if self.is_structured:
            return
        value_str = str(value) if value is not None else "none"
        self._emit_text(f"{name}: {value_str}")

    def header(self, text: str) -> None:
        """Print a section header (text mode only)."""
        if self.is_structured:
            return
        self._emit_text(f"\n{text}")

    def subheader(self, text: str) -> None:
        """Print a subheader (text mode only)."""
        if self.is_structured:
            return
        self._emit_text(text)

    def blank(self) -> None:
        """Print a blank line (text mode only)."""
        if self.is_structured:
            return
        self._emit_text("")

    def state(self, name: str, state: str) -> None:
        """Print a state field (text mode only)."""
        if self.is_structured:
            return
        self._emit_text(f"{name}: {state}")

    def success(self, text: str) -> None:
        """Print a success message (text mode only)."""
        self.line(text)

    def error(self, text: str) -> None:
        """Print an error message."""
        if self.is_structured:
            self.error_obj(code="cli_error", message=text)
            return
        self._print_err(text)

    def warning(self, text: str) -> None:
        """Print a warning message (text mode only)."""
        self.line(text)

    def dim(self, text: str) -> None:
        """Print muted/status text (text mode only)."""
        self.line(text)

    def markdown(self, text: str) -> None:
        """Print markdown content as plain text (text mode only)."""
        if self.is_structured:
            return
        self._emit_text(text)

    def list_item(self, text: str, bullet: str = "•") -> None:
        """Print a list item with bullet (text mode only)."""
        if self.is_structured:
            return
        self._emit_text(f"  {bullet} {text}")
