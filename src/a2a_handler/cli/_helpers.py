"""Shared utilities for CLI commands."""

import os
import sys
from dataclasses import dataclass

import httpx
import click
from a2a.client.errors import (
    A2AClientError,
    A2AClientTimeoutError,
    AgentCardResolutionError,
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
    ServerDefinition,
    load_server_catalog,
    resolve_server_credentials,
)

TIMEOUT = 120
_TIMEOUT_NONE_VALUES = {"none", "null", "off", "disabled"}

_connect_timeout: float | None = float(TIMEOUT)
_read_timeout: float | None = float(TIMEOUT)
_write_timeout: float | None = float(TIMEOUT)
_pool_timeout: float | None = float(TIMEOUT)
_stream_read_timeout: float | None = None
log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AgentSelection:
    """A resolved CLI target without any secret-bearing credentials."""

    agent_url: str
    server_def: ServerDefinition | None = None


def build_http_client(
    timeout: int | float | httpx.Timeout | None = None,
    credentials: AuthCredentials | None = None,
) -> httpx.AsyncClient:
    """Build an HTTP client with the specified timeout."""
    effective_timeout = timeout if timeout is not None else _standard_timeout()
    if credentials and credentials.auth_type == AuthType.MTLS:
        return httpx.AsyncClient(
            timeout=effective_timeout,
            verify=credentials.build_ssl_context(),
            trust_env=False,
        )
    return httpx.AsyncClient(timeout=effective_timeout, trust_env=False)


def build_streaming_http_client(
    credentials: AuthCredentials | None = None,
) -> httpx.AsyncClient:
    """Build an HTTP client for long-lived streaming responses.

    Streaming keeps the usual finite connect/write/pool timeouts but disables
    the read timeout so an active long-running A2A task is not aborted just
    because the server has no SSE event ready for a while.
    """
    return build_http_client(
        timeout=httpx.Timeout(
            connect=_connect_timeout,
            read=_stream_read_timeout,
            write=_write_timeout,
            pool=_pool_timeout,
        ),
        credentials=credentials,
    )


def configure_http_timeouts(
    *,
    connect_timeout: str | int | float | None = None,
    read_timeout: str | int | float | None = None,
    write_timeout: str | int | float | None = None,
    pool_timeout: str | int | float | None = None,
    stream_read_timeout: str | int | float | None = None,
) -> None:
    """Configure default CLI HTTP timeouts.

    Passing no values resets the defaults. String values may be seconds or
    ``none`` to disable that timeout.
    """
    global _connect_timeout, _read_timeout, _write_timeout, _pool_timeout
    global _stream_read_timeout

    _connect_timeout = _parse_timeout_option(
        connect_timeout, "connect-timeout", float(TIMEOUT)
    )
    _read_timeout = _parse_timeout_option(read_timeout, "read-timeout", float(TIMEOUT))
    _write_timeout = _parse_timeout_option(
        write_timeout, "write-timeout", float(TIMEOUT)
    )
    _pool_timeout = _parse_timeout_option(pool_timeout, "pool-timeout", float(TIMEOUT))
    _stream_read_timeout = _parse_timeout_option(
        stream_read_timeout, "stream-read-timeout", None
    )


def _standard_timeout() -> httpx.Timeout:
    """Return the configured timeout for regular request/response calls."""
    return httpx.Timeout(
        connect=_connect_timeout,
        read=_read_timeout,
        write=_write_timeout,
        pool=_pool_timeout,
    )


def _parse_timeout_option(
    value: str | int | float | None,
    field_name: str,
    default: float | None,
) -> float | None:
    """Parse a CLI/env timeout value."""
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        if normalized in _TIMEOUT_NONE_VALUES:
            return None
        try:
            parsed = float(normalized)
        except ValueError as exc:
            raise click.BadParameter(
                "must be a number of seconds or 'none'",
                param_hint=f"--{field_name}",
            ) from exc
    else:
        parsed = float(value)

    if parsed < 0:
        raise click.BadParameter(
            "must be greater than or equal to 0",
            param_hint=f"--{field_name}",
        )
    return parsed


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
    elif isinstance(e, AgentCardResolutionError):
        log.error("Agent card resolution failed for %s: %s", agent_url, e)
        message = f"Could not resolve agent card: {e}"
        error_code = "agent_card_resolution_error"
        suggestion = "Verify the agent URL and that the server exposes an agent card"
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


def _find_named_server(server: str) -> ServerDefinition:
    """Resolve a named server definition, failing closed on ambiguity."""
    catalog = load_server_catalog()
    matches = [
        server_def
        for server_def in (
            *catalog.repository_servers,
            *catalog.global_servers,
        )
        if server_def.name == server
    ]
    if len(matches) > 1:
        raise click.UsageError(
            f"Server '{server}' exists in multiple sources; use --url or rename one entry."
        )
    if matches:
        return matches[0]
    raise click.UsageError(f"Server '{server}' not found in servers.toml.")


def resolve_agent_selection(
    url: str | None,
    server: str | None,
) -> AgentSelection:
    """Resolve the CLI target URL without touching any secrets."""
    if url and server:
        raise click.UsageError("Provide either --url or --server, not both.")
    if url:
        return AgentSelection(agent_url=url)
    if server:
        server_def = _find_named_server(server)
        return AgentSelection(agent_url=server_def.agent_url, server_def=server_def)
    raise click.UsageError("Provide --url or --server.")


def resolve_selection_credentials(
    selection: AgentSelection,
    bearer_env: str | None = None,
    api_key_env: str | None = None,
) -> AuthCredentials | None:
    """Resolve credentials for a previously selected target.

    CLI flag auth (``--bearer-env``, ``--api-key-env``) overrides server auth.
    Misconfigured named-server auth fails closed instead of silently falling back
    to an unauthenticated request.
    """
    bearer_token = (
        _resolve_env_secret(bearer_env, "bearer auth") if bearer_env else None
    )
    api_key = _resolve_env_secret(api_key_env, "API key auth") if api_key_env else None

    if bearer_token:
        return create_bearer_auth(bearer_token)
    if api_key:
        return create_api_key_auth(api_key)
    if selection.server_def is None:
        return None

    credentials, warning = resolve_server_credentials(selection.server_def)
    if warning:
        raise click.UsageError(warning)
    return credentials


def resolve_agent_target(
    url: str | None,
    server: str | None,
    bearer_env: str | None = None,
    api_key_env: str | None = None,
) -> tuple[str, AuthCredentials | None]:
    """Resolve agent URL and credentials from --url or --server flag."""
    selection = resolve_agent_selection(url, server)
    credentials = resolve_selection_credentials(selection, bearer_env, api_key_env)
    return selection.agent_url, credentials


def handle_validation_error(error: InputValidationError, output: Output) -> None:
    """Render input validation errors in the standard envelope."""
    output.error(
        code=error.code,
        message=error.message,
        details=error.details,
        suggestion=error.suggestion,
    )
