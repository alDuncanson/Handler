"""Shared types and constants for server modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import httpx
from a2a.types import AgentCard

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.servers import (
    ServerDefinition,
    ServerSource,
    server_source_label,
)

DEFAULT_HTTP_TIMEOUT_SECONDS = 120
SHORT_ID_LENGTH = 12
RESUME_HISTORY_LENGTH = 100
RECENT_SERVER_LIMIT = 12
MANUAL_SERVER_ID = "__manual__"


class ServerConnectionMode(str, Enum):
    """High-level lifecycle mode for a server."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"


@dataclass(frozen=True, slots=True)
class SavedConversation:
    """Resume metadata loaded from a saved agent session."""

    context_id: str
    task_id: str | None = None


@dataclass(slots=True)
class ServerState:
    """Explicit per-server runtime state."""

    mode: ServerConnectionMode = ServerConnectionMode.DISCONNECTED
    agent_card: AgentCard | None = None
    agent_url: str | None = None
    current_context_id: str | None = None
    current_task_id: str | None = None
    connected_credentials: AuthCredentials | None = None
    auth_source: str = "none"
    auth_overridden: bool = False
    saved_conversation: SavedConversation | None = None
    resumed: bool = False
    connection_summary: str = "Manual URL"


def summarize_identifier(value: str) -> str:
    """Shorten long IDs for compact UI summaries."""
    if len(value) <= SHORT_ID_LENGTH:
        return value
    return f"{value[:SHORT_ID_LENGTH]}..."


def build_http_client(
    timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
    credentials: AuthCredentials | None = None,
) -> httpx.AsyncClient:
    """Build an HTTP client with the specified timeout."""
    if credentials and credentials.auth_type == AuthType.MTLS:
        return httpx.AsyncClient(
            timeout=timeout_seconds,
            verify=credentials.build_ssl_context(),
        )
    return httpx.AsyncClient(timeout=timeout_seconds)


def build_recent_server(agent_url: str) -> ServerDefinition:
    """Create a runtime-only server option for recent usage."""
    return ServerDefinition(
        server_id=f"recent:{agent_url}",
        source=ServerSource.RECENT,
        name=None,
        agent_url=agent_url,
        origin_label=server_source_label(ServerSource.RECENT),
    )
