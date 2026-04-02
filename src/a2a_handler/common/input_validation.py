"""Input validation utilities for agent-facing surfaces.

These checks intentionally guard against common LLM-generated malformed inputs.
"""

from __future__ import annotations

import json
import os
import stat
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


_RESERVED_HEADER_NAMES = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "te",
        "trailer",
        "upgrade",
        "expect",
        "authorization",
        "cookie",
        "proxy-authorization",
        "proxy-connection",
    }
)


def validate_header_name(name: str, field_name: str = "header") -> str:
    """Reject reserved or dangerous HTTP header names."""
    reject_control_chars(name, field_name)
    if name.lower() in _RESERVED_HEADER_NAMES:
        raise InputValidationError(
            code="reserved_header",
            message=f"{field_name} must not set reserved header '{name}'",
            suggestion="Remove this header; authentication headers are managed automatically",
            details={"field": field_name, "header": name},
        )
    return name


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def validate_token_url(token_url: str) -> str:
    """Validate an OAuth2 token endpoint URL.

    Requires HTTPS except for loopback addresses used in development.
    """
    reject_control_chars(token_url, "token_url")
    parsed = urlparse(token_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InputValidationError(
            code="invalid_token_url",
            message="token_url must be a valid http(s) URL",
            suggestion="Use a full URL like https://auth.example.com/oauth/token",
            details={"field": "token_url"},
        )
    hostname = parsed.hostname or ""
    if parsed.scheme == "http" and hostname not in _LOOPBACK_HOSTS:
        raise InputValidationError(
            code="insecure_token_url",
            message="token_url must use HTTPS for non-loopback hosts",
            suggestion="Use https:// to protect OAuth2 client credentials in transit",
            details={"field": "token_url"},
        )
    return token_url


def check_key_file_permissions(key_path: str, field_name: str = "key_path") -> None:
    """Warn if a private key file has overly permissive permissions.

    Raises InputValidationError if the key is readable by group or others.
    Silently passes on platforms where permission checks are not meaningful.
    """
    try:
        mode = stat.S_IMODE(os.stat(key_path).st_mode)
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        raise InputValidationError(
            code="insecure_key_permissions",
            message=f"Private key '{key_path}' is readable by group or others",
            suggestion="Run: chmod 600 " + key_path,
            details={"field": field_name, "mode": oct(mode)},
        )
