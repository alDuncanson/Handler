"""Simple output formatting system for CLI.

Provides styled console output with ANSI colors.
"""

from __future__ import annotations

import json as json_module
import sys
from typing import Any, Literal, TextIO

TERMINAL_STATES = {"completed", "failed", "canceled", "rejected"}
SUCCESS_STATES = {"completed"}
ERROR_STATES = {"failed", "rejected"}
WARNING_STATES = {"canceled"}

# Basic ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"

OutputFormat = Literal["text", "json", "ndjson"]

_DEFAULT_OUTPUT_FORMAT: OutputFormat = "text"
_DEFAULT_QUIET = False


def configure_output(output_format: OutputFormat = "text", quiet: bool = False) -> None:
    """Configure default output behavior for CLI commands."""
    global _DEFAULT_OUTPUT_FORMAT, _DEFAULT_QUIET
    _DEFAULT_OUTPUT_FORMAT = output_format
    _DEFAULT_QUIET = quiet


def _supports_color(stream: TextIO) -> bool:
    """Check if the stream supports ANSI colors."""
    if not hasattr(stream, "isatty"):
        return False
    if not stream.isatty():
        return False
    return True


class Output:
    """Manages styled console output.

    Provides a unified interface for outputting text, fields, JSON, and
    markdown with automatic color formatting when supported.
    """

    def __init__(
        self,
        output_format: OutputFormat | None = None,
        quiet: bool | None = None,
    ) -> None:
        self._use_color = _supports_color(sys.stdout)
        self._output_format: OutputFormat = output_format or _DEFAULT_OUTPUT_FORMAT
        self._quiet = _DEFAULT_QUIET if quiet is None else quiet

    def _style(self, text: str, *codes: str) -> str:
        """Apply ANSI codes if color is enabled."""
        if not self._use_color or not codes:
            return text
        return "".join(codes) + text + RESET

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

    def line(self, text: str, style: str | None = None) -> None:
        """Print a line of text with optional style."""
        if self._output_format != "text":
            self._emit_structured({"type": "line", "text": text, "style": style})
            return
        if style and self._use_color:
            code = {
                "green": GREEN,
                "red": RED,
                "yellow": YELLOW,
                "cyan": CYAN,
                "dim": DIM,
                "bold": BOLD,
            }.get(style, "")
            text = self._style(text, code)
        self._emit_text(text)

    def field(
        self,
        name: str,
        value: Any,
        dim_value: bool = False,
        value_style: str | None = None,
    ) -> None:
        """Print a field as 'Name: value' with formatting."""
        value_str = str(value) if value is not None else "none"
        if self._output_format != "text":
            self._emit_structured(
                {
                    "type": "field",
                    "name": name,
                    "value": value,
                    "dim_value": dim_value,
                    "value_style": value_style,
                }
            )
            return
        name_part = self._style(f"{name}:", BOLD) if self._use_color else f"{name}:"

        if self._use_color:
            if value_style:
                code = {"green": GREEN, "red": RED, "cyan": CYAN}.get(value_style, "")
                value_part = self._style(value_str, code)
            elif dim_value:
                value_part = self._style(value_str, DIM)
            else:
                value_part = value_str
        else:
            value_part = value_str

        self._emit_text(f"{name_part} {value_part}")

    def header(self, text: str) -> None:
        """Print a section header."""
        if self._output_format != "text":
            self._emit_structured({"type": "header", "text": text})
            return
        styled = self._style(text, BOLD) if self._use_color else text
        self._emit_text(f"\n{styled}")

    def subheader(self, text: str) -> None:
        """Print a subheader (less prominent than header)."""
        if self._output_format != "text":
            self._emit_structured({"type": "subheader", "text": text})
            return
        styled = self._style(text, BOLD, CYAN) if self._use_color else text
        self._emit_text(styled)

    def blank(self) -> None:
        """Print a blank line."""
        if self._output_format != "text":
            self._emit_structured({"type": "blank"})
            return
        self._emit_text("")

    def state(self, name: str, state: str) -> None:
        """Print a state field with appropriate coloring."""
        lower = state.lower()
        if self._output_format != "text":
            self._emit_structured({"type": "state", "name": name, "state": state})
            return
        if lower in SUCCESS_STATES:
            style = "green"
        elif lower in ERROR_STATES:
            style = "red"
        elif lower in WARNING_STATES:
            style = "yellow"
        else:
            style = "cyan"

        name_part = self._style(f"{name}:", BOLD) if self._use_color else f"{name}:"
        code = {"green": GREEN, "red": RED, "yellow": YELLOW, "cyan": CYAN}.get(
            style, ""
        )
        value_part = self._style(state, code) if self._use_color else state
        self._emit_text(f"{name_part} {value_part}")

    def success(self, text: str) -> None:
        """Print a success message."""
        self.line(text, "green")

    def error(self, text: str) -> None:
        """Print an error message."""
        if self._output_format != "text":
            self.error_obj(code="cli_error", message=text)
            return
        styled = self._style(text, RED, BOLD) if self._use_color else text
        self._emit_text(styled, force=True)

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
        self.line(text, "yellow")

    def dim(self, text: str) -> None:
        """Print dimmed/muted text."""
        self.line(text, "dim")

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
