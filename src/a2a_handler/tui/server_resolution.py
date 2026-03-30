"""Pure server and session resolution logic for the TUI server."""

from __future__ import annotations

from a2a_handler.auth import AuthCredentials
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    validate_resource_id,
)
from a2a_handler.servers import (
    ServerDefinition,
    ServerSource,
    server_source_label,
)
from a2a_handler.session import AgentSession
from a2a_handler.tui.server_types import SavedConversation

logger = get_logger(__name__)


def resolve_server_auth(
    selected_server: ServerDefinition | None,
    override_credentials: AuthCredentials | None,
    server_credentials: dict[str, AuthCredentials],
    server_warnings: dict[str, str],
) -> tuple[AuthCredentials | None, str, str | None]:
    """Resolve connect-time credentials automatically.

    Priority: override credentials → server default → none.
    """
    if override_credentials is not None:
        return override_credentials, "manual override", None

    if selected_server is None:
        return None, "none", None

    credentials = server_credentials.get(selected_server.server_id)
    if credentials is not None:
        return (
            credentials,
            (
                f"{selected_server.origin_label.lower()} server "
                f"'{selected_server.label}' default"
            ),
            None,
        )

    warning = server_warnings.get(selected_server.server_id)
    if warning:
        return (
            None,
            (
                f"{selected_server.origin_label.lower()} server "
                f"'{selected_server.label}' default unavailable"
            ),
            warning,
        )

    return (
        None,
        (
            f"{selected_server.origin_label.lower()} server "
            f"'{selected_server.label}' (no default auth)"
        ),
        None,
    )


def build_server_summary(
    selected_server: ServerDefinition | None,
    agent_url: str,
) -> str:
    """Build a human-readable server summary string."""
    if selected_server is not None:
        return f"{selected_server.origin_label} · {selected_server.label}"
    return f"Manual URL · {agent_url}"


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
