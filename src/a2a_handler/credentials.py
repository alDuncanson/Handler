"""Credential resolution helpers for CLI, TUI, and MCP surfaces."""

from __future__ import annotations

import os
import shlex
import subprocess

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_api_key_auth,
    create_bearer_auth,
)
from a2a_handler.common import (
    get_agent_bearer_command,
    get_default_bearer_command,
    get_logger,
)
from a2a_handler.common.input_validation import (
    InputValidationError,
    reject_control_chars,
)
from a2a_handler.session import get_credentials

logger = get_logger(__name__)

DEFAULT_BEARER_COMMAND_ENV = "HANDLER_BEARER_COMMAND"
BUILTIN_BEARER_PROVIDERS: dict[str, str] = {
    "gcloud": "gcloud auth print-identity-token",
}


def get_builtin_provider_command(provider: str) -> str | None:
    """Return the built-in token command for a provider name."""
    return BUILTIN_BEARER_PROVIDERS.get(provider)


def resolve_configured_bearer_command(agent_url: str) -> tuple[str, str] | None:
    """Resolve configured bearer command and its source.

    Precedence:
    1. Per-agent command from config
    2. Global default command from config
    3. Environment variable fallback (HANDLER_BEARER_COMMAND)
    """
    if command := get_agent_bearer_command(agent_url):
        return command, "agent"
    if command := get_default_bearer_command():
        return command, "default"
    if command := os.getenv(DEFAULT_BEARER_COMMAND_ENV):
        return command, "env"
    return None


def _token_from_command(command: str) -> str:
    """Execute a command and return bearer token output."""
    reject_control_chars(command, "bearer_command")

    try:
        command_parts = shlex.split(command)
    except ValueError as error:
        raise InputValidationError(
            code="invalid_bearer_command",
            message=f"Invalid bearer command: {error}",
            suggestion="Provide a valid shell command string",
        ) from error

    if not command_parts:
        raise InputValidationError(
            code="empty_bearer_command",
            message="bearer_command cannot be empty",
            suggestion="Provide a command that prints a token to stdout",
        )

    try:
        command_result = subprocess.run(
            command_parts,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.strip() if error.stderr else ""
        message = f"bearer_command failed with exit code {error.returncode}"
        if stderr:
            message = f"{message}: {stderr}"
        raise InputValidationError(
            code="bearer_command_failed",
            message=message,
            suggestion="Verify CLI login and command arguments",
        ) from error

    token = command_result.stdout.strip()
    if not token:
        raise InputValidationError(
            code="empty_bearer_token",
            message="bearer_command produced an empty token",
            suggestion="Use a command that prints only a token to stdout",
        )

    reject_control_chars(token, "bearer_token")
    return token


def resolve_auth_credentials(
    agent_url: str,
    bearer_token: str | None = None,
    api_key: str | None = None,
    bearer_command: str | None = None,
) -> AuthCredentials | None:
    """Resolve credentials from explicit inputs, config sources, and keyring.

    Precedence:
    1. Explicit bearer token
    2. Explicit API key
    3. Explicit bearer command
    4. Configured bearer command (per-agent/default/env)
    5. Saved credentials from keyring-backed session data
    """
    if bearer_token:
        reject_control_chars(bearer_token, "bearer_token")
        return create_bearer_auth(bearer_token)

    if api_key:
        reject_control_chars(api_key, "api_key")
        return create_api_key_auth(api_key)

    command = bearer_command
    command_source = "explicit"
    if command is None:
        configured = resolve_configured_bearer_command(agent_url)
        if configured is not None:
            command, command_source = configured

    if command:
        token = _token_from_command(command)
        logger.debug(
            "Resolved bearer token via %s command for %s",
            command_source,
            agent_url,
        )
        return create_bearer_auth(token)

    credentials = get_credentials(agent_url)
    if credentials and credentials.auth_type == AuthType.BEARER:
        logger.debug("Using saved bearer credentials for %s", agent_url)
    elif credentials and credentials.auth_type == AuthType.API_KEY:
        logger.debug("Using saved API key credentials for %s", agent_url)
    return credentials
