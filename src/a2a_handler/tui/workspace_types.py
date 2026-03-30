"""Shared types and constants for workspace modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import httpx
from a2a.types import AgentCard

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.connections import (
    ConnectionDefinition,
    ConnectionSource,
    connection_source_label,
)

DEFAULT_HTTP_TIMEOUT_SECONDS = 120
SHORT_ID_LENGTH = 12
RESUME_HISTORY_LENGTH = 100
RECENT_CONNECTION_LIMIT = 12
EMPTY_CONNECTION_ID = "__empty__"

CONFIGURED_CONNECTION_SOURCES = (
    ConnectionSource.REPOSITORY,
    ConnectionSource.GLOBAL,
    ConnectionSource.RECENT,
)
CONNECTION_SOURCE_ORDER = (*CONFIGURED_CONNECTION_SOURCES, ConnectionSource.MANUAL)
EMPTY_SOURCE_LABELS = {
    ConnectionSource.REPOSITORY: "No repository connections configured",
    ConnectionSource.GLOBAL: "No global connections configured",
    ConnectionSource.RECENT: "No recent connections yet",
}
SOURCE_OPTIONS = [
    (connection_source_label(source), source.value)
    for source in CONNECTION_SOURCE_ORDER
]
AUTH_MODE_OPTIONS = [
    ("Default auth", "use_connection_default"),
    ("Override auth", "override"),
]
START_FRESH_OPTION = [("Fresh", "start_fresh")]
SAVED_SESSION_OPTIONS = [("Resume", "resume_session"), *START_FRESH_OPTION]


class WorkspaceConnectionMode(str, Enum):
    """High-level lifecycle mode for a remote workspace."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"


class WorkspaceLaunchMode(str, Enum):
    """How a workspace should initialize its conversation state."""

    START_FRESH = "start_fresh"
    RESUME_SESSION = "resume_session"


class WorkspaceAuthMode(str, Enum):
    """How connect-time auth should be chosen for a workspace."""

    USE_CONNECTION_DEFAULT = "use_connection_default"
    OVERRIDE = "override"


@dataclass(frozen=True, slots=True)
class SavedConversation:
    """Resume metadata loaded from a saved agent session."""

    context_id: str
    task_id: str | None = None


@dataclass(slots=True)
class WorkspaceState:
    """Explicit per-workspace runtime state."""

    mode: WorkspaceConnectionMode = WorkspaceConnectionMode.DISCONNECTED
    agent_card: AgentCard | None = None
    agent_url: str | None = None
    current_context_id: str | None = None
    current_task_id: str | None = None
    connected_credentials: AuthCredentials | None = None
    auth_source: str = "none"
    auth_mode: WorkspaceAuthMode = WorkspaceAuthMode.USE_CONNECTION_DEFAULT
    launch_mode: WorkspaceLaunchMode = WorkspaceLaunchMode.START_FRESH
    saved_conversation: SavedConversation | None = None
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


def build_recent_connection(agent_url: str) -> ConnectionDefinition:
    """Create a runtime-only connection option for recent usage."""
    return ConnectionDefinition(
        connection_id=f"recent:{agent_url}",
        source=ConnectionSource.RECENT,
        name=None,
        agent_url=agent_url,
        origin_label=connection_source_label(ConnectionSource.RECENT),
    )
