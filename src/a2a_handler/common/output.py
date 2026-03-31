"""Simple output formatting system for CLI.

Provides plain text and structured JSON/NDJSON output.
"""

from __future__ import annotations

import json as json_module
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

    Provides a unified interface for outputting text, fields, JSON, and
    markdown in plain text or structured formats.
    """

    def __init__(
        self,
        output_format: OutputFormat | None = None,
        quiet: bool | None = None,
    ) -> None:
        self._output_format: OutputFormat = output_format or _DEFAULT_OUTPUT_FORMAT
        self._quiet = _DEFAULT_QUIET if quiet is None else quiet

    def _print(self, text: str) -> None:
        """Print text to stdout."""
        print(text)

    def _emit_text(self, text: str, force: bool = False) -> None:
        """Print plain text output with quiet-mode handling."""
        if self._quiet and not force:
            return
        self._print(text)

    def _emit_structured(self, payload: dict[str, Any], force: bool = False) -> None:
        """Emit structured output in json/ndjson mode."""
        if self._quiet and not force:
            return
        if self._output_format == "ndjson":
            self._print(json_module.dumps(payload, default=str))
        else:
            self._print(json_module.dumps(payload, indent=2, default=str))

    def line(self, text: str) -> None:
        """Print a line of text."""
        if self._output_format != "text":
            self._emit_structured({"type": "line", "text": text})
            return
        self._emit_text(text)

    def field(self, name: str, value: Any) -> None:
        """Print a field as 'Name: value'."""
        value_str = str(value) if value is not None else "none"
        if self._output_format != "text":
            self._emit_structured(
                {"type": "field", "name": name, "value": value}
            )
            return
        self._emit_text(f"{name}: {value_str}")

    def header(self, text: str) -> None:
        """Print a section header."""
        if self._output_format != "text":
            self._emit_structured({"type": "header", "text": text})
            return
        self._emit_text(f"\n{text}")

    def subheader(self, text: str) -> None:
        """Print a subheader (less prominent than header)."""
        if self._output_format != "text":
            self._emit_structured({"type": "subheader", "text": text})
            return
        self._emit_text(text)

    def blank(self) -> None:
        """Print a blank line."""
        if self._output_format != "text":
            self._emit_structured({"type": "blank"})
            return
        self._emit_text("")

    def state(self, name: str, state: str) -> None:
        """Print a state field."""
        if self._output_format != "text":
            self._emit_structured({"type": "state", "name": name, "state": state})
            return
        self._emit_text(f"{name}: {state}")

    def success(self, text: str) -> None:
        """Print a success message."""
        self.line(text)

    def error(self, text: str) -> None:
        """Print an error message."""
        if self._output_format != "text":
            self.error_obj(code="cli_error", message=text)
            return
        self._emit_text(text, force=True)

    def error_obj(
        self,
        code: str,
        message: str,
        details: Any | None = None,
        suggestion: str | None = None,
    ) -> None:
        """Print a standardized error envelope.

        In text mode this prints the message only; in structured modes it emits a
        stable error object that downstream agents can parse.
        """
        if self._output_format == "text":
            self.error(message)
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
        self._emit_structured(payload, force=True)

    def warning(self, text: str) -> None:
        """Print a warning message."""
        self.line(text)

    def dim(self, text: str) -> None:
        """Print muted text."""
        self.line(text)

    def json(self, data: Any) -> None:
        """Print JSON data."""
        if self._output_format == "text":
            json_str = json_module.dumps(data, indent=2, default=str)
            self._emit_text(json_str)
            return
        self._emit_structured({"type": "data", "data": data})

    def markdown(self, text: str) -> None:
        """Print markdown content (as plain text)."""
        if self._output_format != "text":
            self._emit_structured({"type": "markdown", "text": text})
            return
        self._emit_text(text)

    def list_item(self, text: str, bullet: str = "•") -> None:
        """Print a list item with bullet."""
        if self._output_format != "text":
            self._emit_structured({"type": "list_item", "text": text, "bullet": bullet})
            return
        self._emit_text(f"  {bullet} {text}")
