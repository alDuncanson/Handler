"""Pure server and session resolution logic for the TUI server."""

from __future__ import annotations

from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    validate_resource_id,
)
from a2a_handler.session import AgentSession
from a2a_handler.tui.server_types import SavedConversation

logger = get_logger(__name__)


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
        logger.warning("Ignoring saved context for %s: %s", agent_url, error.message)
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
