"""Shared utilities for CLI commands."""

import httpx
import rich_click as click
from a2a.client.errors import (
    A2AClientError,
    A2AClientHTTPError,
    A2AClientTimeoutError,
)

from a2a_handler.common import Output, get_logger

TIMEOUT = 120
log = get_logger(__name__)


def build_http_client(timeout: int = TIMEOUT) -> httpx.AsyncClient:
    """Build an HTTP client with the specified timeout."""
    return httpx.AsyncClient(timeout=timeout)


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
        output.error_obj(
            code=error_code,
            message=message,
            details=details,
            suggestion=suggestion,
        )
    else:
        click.echo(f"Error [{error_code}]: {message}", err=True)
