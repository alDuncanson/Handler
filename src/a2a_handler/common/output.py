"""Output system for CLI.

All command output is structured JSON or NDJSON.  Errors are emitted to
stderr as JSON.
"""

from __future__ import annotations

import json as json_module
import sys
from typing import Any, Literal

OutputFormat = Literal["json", "ndjson"]

_DEFAULT_OUTPUT_FORMAT: OutputFormat = "json"
_DEFAULT_QUIET = False


def configure_output(output_format: OutputFormat = "json", quiet: bool = False) -> None:
    """Configure default output behavior for CLI commands."""
    global _DEFAULT_OUTPUT_FORMAT, _DEFAULT_QUIET
    _DEFAULT_OUTPUT_FORMAT = output_format
    _DEFAULT_QUIET = quiet


class Output:
    """Emits structured JSON/NDJSON to stdout, errors to stderr."""

    def __init__(
        self,
        output_format: OutputFormat | None = None,
        quiet: bool | None = None,
    ) -> None:
        self._output_format: OutputFormat = output_format or _DEFAULT_OUTPUT_FORMAT
        self._quiet = _DEFAULT_QUIET if quiet is None else quiet

    def json(self, data: Any) -> None:
        """Emit a domain object to stdout."""
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
        else:
            print(json_module.dumps(payload, indent=2, default=str), file=sys.stderr)
