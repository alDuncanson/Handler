"""Shared utilities for CLI commands."""

import os
import sys

import httpx
import click
from a2a.client.errors import (
    A2AClientError,
    A2AClientHTTPError,
    A2AClientTimeoutError,
)

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_api_key_auth,
    create_bearer_auth,
)
from a2a_handler.common import Output, get_logger
from a2a_handler.common.input_validation import InputValidationError
from a2a_handler.servers import (
    load_server_catalog,
    resolve_server_credentials,
)

TIMEOUT = 120
log = get_logger(__name__)


def build_http_client(
    timeout: int = TIMEOUT,
    credentials: AuthCredentials | None = None,
) -> httpx.AsyncClient:
    """Build an HTTP client with the specified timeout."""
    if credentials and credentials.auth_type == AuthType.MTLS:
        return httpx.AsyncClient(
            timeout=timeout,
            verify=credentials.build_ssl_context(),
            trust_env=False,
        )
    return httpx.AsyncClient(timeout=timeout, trust_env=False)


def handle_client_error(e: Exception, agent_url: str, output: Output | None) -> None:
    """Handle A2A client errors with appropriate messages."""
    message = ""
    error_code = "unexpected_error"
    details: dict[str, object] | None = None
    suggestion: str | None = None
    if isinstance(e, A2AClientTimeoutError):
        log.error("Request to %s timed out", agent_url)
        message = "Request timed out"
        error_code = "request_timeout"
        suggestion = "Retry the request or increase timeout settings"
    elif isinstance(e, A2AClientHTTPError):
        log.error("A2A client error: %s", e)
        if "connection" in str(e).lower():
            message = f"Connection failed: Is the server running at {agent_url}?"
            error_code = "connection_failed"
            suggestion = "Verify the agent URL and that the server is reachable"
        else:
            message = str(e)
            error_code = "a2a_http_error"
        details = {"agent_url": agent_url}
    elif isinstance(e, A2AClientError):
        log.error("A2A client error: %s", e)
        message = str(e)
        error_code = "a2a_client_error"
    elif isinstance(e, httpx.ConnectError):
        log.error("Connection refused to %s", agent_url)
        message = f"Connection refused: Is the server running at {agent_url}?"
        error_code = "connection_refused"
        suggestion = "Verify the agent URL and that the server is reachable"
    elif isinstance(e, httpx.TimeoutException):
        log.error("Request to %s timed out", agent_url)
        message = "Request timed out"
        error_code = "request_timeout"
        suggestion = "Retry the request or increase timeout settings"
    elif isinstance(e, httpx.HTTPStatusError):
        log.error("HTTP error %d from %s", e.response.status_code, agent_url)
        message = f"HTTP {e.response.status_code} - {e.response.text}"
        error_code = "http_status_error"
        details = {
            "status_code": e.response.status_code,
            "agent_url": agent_url,
        }
    else:
        log.exception("Failed request to %s", agent_url)
        message = str(e)
        error_code = "unexpected_error"

    if output:
        output.error(
            code=error_code,
            message=message,
            details=details,
            suggestion=suggestion,
        )
    else:
        print(f"Error [{error_code}]: {message}", file=sys.stderr)


def _resolve_env_secret(env_var: str, label: str) -> str:
    """Read a secret from an environment variable."""
    value = os.environ.get(env_var)
    if not value:
        raise click.UsageError(
            f"Environment variable {env_var} is not set (needed for {label})"
        )
    return value


def resolve_agent_target(
    url: str | None,
    server: str | None,
    bearer_env: str | None = None,
    api_key_env: str | None = None,
) -> tuple[str, AuthCredentials | None]:
    """Resolve agent URL and credentials from --url or --server flag.

    CLI flag auth (``--bearer-env``, ``--api-key-env``) overrides server auth.
    """
    if url and server:
        raise click.UsageError("Provide either --url or --server, not both.")

    bearer_token = (
        _resolve_env_secret(bearer_env, "bearer auth") if bearer_env else None
    )
    api_key = _resolve_env_secret(api_key_env, "API key auth") if api_key_env else None

    if url:
        credentials: AuthCredentials | None = None
        if bearer_token:
            credentials = create_bearer_auth(bearer_token)
        elif api_key:
            credentials = create_api_key_auth(api_key)
        return url, credentials

    if server:
        catalog = load_server_catalog()
        for server_def in (
            *catalog.repository_servers,
            *catalog.global_servers,
        ):
            if server_def.name == server:
                if bearer_token:
                    return server_def.agent_url, create_bearer_auth(bearer_token)
                if api_key:
                    return server_def.agent_url, create_api_key_auth(api_key)
                creds, warning = resolve_server_credentials(server_def)
                if warning:
                    log.warning(warning)
                return server_def.agent_url, creds
        raise click.UsageError(f"Server '{server}' not found in servers.toml.")

    raise click.UsageError("Provide --url or --server.")


def handle_validation_error(error: InputValidationError, output: Output) -> None:
    """Render input validation errors in the standard envelope."""
    output.error(
        code=error.code,
        message=error.message,
        details=error.details,
        suggestion=error.suggestion,
    )
