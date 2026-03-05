"""Input validation utilities for agent-facing surfaces.

These checks intentionally guard against common LLM-generated malformed inputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(slots=True)
class InputValidationError(ValueError):
    """Raised when a CLI or MCP input fails validation."""

    code: str
    message: str
    suggestion: str | None = None
    details: dict[str, object] | None = None


def reject_control_chars(value: str, field_name: str) -> None:
    """Reject ASCII control characters in user-provided values."""
    for char in value:
        if ord(char) < 0x20:
            raise InputValidationError(
                code="invalid_control_chars",
                message=f"{field_name} contains unsupported control characters",
                suggestion="Remove invisible characters and retry",
                details={"field": field_name},
            )


def validate_agent_url(agent_url: str) -> str:
    """Validate an agent URL expected to be http(s)."""
    reject_control_chars(agent_url, "agent_url")
    parsed = urlparse(agent_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InputValidationError(
            code="invalid_agent_url",
            message="agent_url must be a valid http(s) URL",
            suggestion="Use a full URL like http://localhost:8000",
            details={"field": "agent_url"},
        )
    return agent_url


def validate_resource_id(value: str, field_name: str) -> str:
    """Validate resource identifiers (task/context/config IDs)."""
    reject_control_chars(value, field_name)
    if any(char in value for char in ("?", "#", "%")):
        raise InputValidationError(
            code="invalid_resource_id",
            message=f"{field_name} contains reserved URL characters",
            suggestion="Pass only the raw identifier without query fragments or encoding",
            details={"field": field_name},
        )
    return value


def validate_webhook_url(url: str) -> str:
    """Validate webhook callback URLs used for push notifications."""
    reject_control_chars(url, "webhook_url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InputValidationError(
            code="invalid_webhook_url",
            message="Webhook URL must be a valid http(s) URL",
            suggestion="Use a full URL like https://example.com/webhook",
            details={"field": "webhook_url"},
        )
    return url


def parse_json_object(raw: str, field_name: str) -> dict[str, object]:
    """Parse a JSON object string and validate its shape."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputValidationError(
            code="invalid_json",
            message=f"{field_name} is not valid JSON",
            suggestion="Provide a valid JSON object payload",
            details={"field": field_name, "error": str(exc)},
        ) from exc

    if not isinstance(parsed, dict):
        raise InputValidationError(
            code="invalid_json_type",
            message=f"{field_name} must be a JSON object",
            suggestion="Wrap payload values in a JSON object",
            details={"field": field_name},
        )
    return parsed


def reject_unknown_keys(
    payload: dict[str, object], allowed_keys: set[str], field_name: str
) -> None:
    """Reject unknown keys in JSON payload flags to prevent silent mistakes."""
    unknown = sorted(set(payload) - allowed_keys)
    if unknown:
        raise InputValidationError(
            code="unknown_payload_keys",
            message=f"{field_name} contains unsupported keys: {', '.join(unknown)}",
            suggestion="Remove unknown keys or use supported command options",
            details={"field": field_name, "unknown_keys": unknown},
        )
