"""Pure connection and session resolution logic for the TUI server."""

from __future__ import annotations

from a2a_handler.auth import AuthCredentials
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    validate_resource_id,
)
from a2a_handler.connections import (
    ConnectionDefinition,
    ConnectionSource,
    connection_source_label,
)
from a2a_handler.session import AgentSession
from a2a_handler.tui.server_types import SavedConversation, ServerAuthMode

logger = get_logger(__name__)


def resolve_workspace_credentials(
    selected_connection: ConnectionDefinition | None,
    active_source: ConnectionSource,
    auth_mode: ServerAuthMode,
    override_credentials: AuthCredentials | None,
    connection_credentials: dict[str, AuthCredentials],
    connection_warnings: dict[str, str],
) -> tuple[AuthCredentials | None, str, str | None]:
    """Resolve connect-time credentials from explicit source selection."""
    if auth_mode == ServerAuthMode.OVERRIDE:
        if override_credentials is not None:
            return override_credentials, "manual override", None
        return None, "manual override (none)", None

    if selected_connection is None:
        if active_source == ConnectionSource.MANUAL:
            return None, "manual URL (no default auth)", None
        return (
            None,
            f"{connection_source_label(active_source)} connection unavailable",
            None,
        )

    credentials = connection_credentials.get(selected_connection.connection_id)
    if credentials is not None:
        return (
            credentials,
            (
                f"{selected_connection.origin_label.lower()} connection "
                f"'{selected_connection.label}' default"
            ),
            None,
        )

    warning = connection_warnings.get(selected_connection.connection_id)
    if warning:
        return (
            None,
            (
                f"{selected_connection.origin_label.lower()} connection "
                f"'{selected_connection.label}' default unavailable"
            ),
            warning,
        )

    return (
        None,
        (
            f"{selected_connection.origin_label.lower()} connection "
            f"'{selected_connection.label}' (no default auth)"
        ),
        None,
    )


def build_connection_summary(
    selected_connection: ConnectionDefinition | None,
    active_source: ConnectionSource,
    agent_url: str,
) -> str:
    """Build a human-readable connection summary string."""
    if selected_connection is not None:
        return f"{selected_connection.origin_label} · {selected_connection.label}"
    if active_source == ConnectionSource.MANUAL:
        return f"Manual URL · {agent_url}"
    return connection_source_label(active_source)


def build_selection_summary(
    selected_connection: ConnectionDefinition | None,
    active_source: ConnectionSource,
    agent_url: str,
) -> str:
    """Build a status summary for the current connection selection."""
    source_label = connection_source_label(active_source)

    if selected_connection is not None:
        return f"{source_label} · {selected_connection.label}"
    if active_source == ConnectionSource.MANUAL:
        if agent_url:
            return "Manual URL"
        return "Manual URL · URL not set"
    return f"{source_label} · unavailable"


def resolve_saved_conversation(
    session: AgentSession | None,
    agent_url: str,
) -> tuple[SavedConversation | None, str | None]:
    """Resolve a saved conversation from a session store entry."""
    if session is None or not session.context_id:
        return None, None

    try:
        validate_resource_id(session.context_id, "context_id")
    except InputValidationError as error:
        logger.warning(
            "Ignoring saved context for %s: %s", agent_url, error.message
        )
        warning = f"saved session ignored: {error.message}"
        if error.suggestion:
            warning = f"saved session ignored: {error.message}. {error.suggestion}"
        return None, warning

    task_id = session.task_id
    if task_id:
        try:
            validate_resource_id(task_id, "task_id")
        except InputValidationError as error:
            logger.warning(
                "Ignoring saved task ID for %s: %s", agent_url, error.message
            )
            task_id = None

    return SavedConversation(context_id=session.context_id, task_id=task_id), None
