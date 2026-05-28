"""Output system for CLI.

Commands default to text mode when they provide a human-readable formatter.
Structured JSON and NDJSON are available for automation through the global
``--output`` option.
"""

from __future__ import annotations

import json as json_module
import sys
from typing import Any, Literal

OutputFormat = Literal["text", "json", "ndjson"]

_DEFAULT_OUTPUT_FORMAT: OutputFormat = "text"
_DEFAULT_QUIET = False


def configure_output(output_format: OutputFormat = "text", quiet: bool = False) -> None:
    """Configure default output behavior for CLI commands."""
    global _DEFAULT_OUTPUT_FORMAT, _DEFAULT_QUIET
    _DEFAULT_OUTPUT_FORMAT = output_format
    _DEFAULT_QUIET = quiet


class Output:
    """Emit CLI output in text, JSON, or NDJSON format."""

    def __init__(
        self,
        output_format: OutputFormat | None = None,
        quiet: bool | None = None,
    ) -> None:
        self._output_format: OutputFormat = output_format or _DEFAULT_OUTPUT_FORMAT
        self._quiet = _DEFAULT_QUIET if quiet is None else quiet

    @property
    def output_format(self) -> OutputFormat:
        """Return the active output format."""
        return self._output_format

    @property
    def is_structured(self) -> bool:
        """Whether output should be structured for machine consumers."""
        return self._output_format in {"json", "ndjson"}

    def text(self, text: str = "", *, end: str = "\n", flush: bool = False) -> None:
        """Emit human-readable text to stdout."""
        if self._quiet:
            return
        print(text, end=end, flush=flush)

    def json(self, data: Any) -> None:
        """Emit a domain object to stdout as JSON/NDJSON."""
        if self._quiet:
            return
        if self._output_format == "ndjson":
            print(json_module.dumps(data, default=str))
        else:
            print(json_module.dumps(data, indent=2, default=str))

    def error(
        self,
        code: str,
        message: str,
        details: Any | None = None,
        suggestion: str | None = None,
    ) -> None:
        """Emit a structured error to stderr (always emitted, ignores quiet)."""
        payload: dict[str, Any] = {
            "type": "error",
            "code": code,
            "message": message,
        }
        if details is not None:
            payload["details"] = details
        if suggestion:
            payload["suggestion"] = suggestion
        if self._output_format == "ndjson":
            print(json_module.dumps(payload, default=str), file=sys.stderr)
        elif self._output_format == "json":
            print(json_module.dumps(payload, indent=2, default=str), file=sys.stderr)
        else:
            print(f"Error: {message}", file=sys.stderr)
            if details is not None:
                print(f"Details: {_format_text_data(details)}", file=sys.stderr)
            if suggestion:
                print(f"Suggestion: {suggestion}", file=sys.stderr)


def _format_text_data(data: Any, indent: int = 0) -> str:
    """Format arbitrary JSON-compatible data as readable plain text."""
    prefix = " " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_format_text_data(value, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {value}")
        return "\n".join(lines)
    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(_format_text_data(item, indent + 2))
            else:
                lines.append(f"{prefix}- {item}")
        return "\n".join(lines)
    return f"{prefix}{data}"
