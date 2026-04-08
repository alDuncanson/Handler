"""Tests for TUI session resume resolution."""

from a2a_handler.session import AgentSession
from a2a_handler.tui.server.session import resolve_saved_conversation


def test_resolve_saved_conversation_drops_invalid_task_id() -> None:
    """Invalid saved task IDs should not block resuming the saved context."""
    saved, warning = resolve_saved_conversation(
        AgentSession(
            agent_url="https://agent.example.com",
            context_id="ctx-valid-123",
            task_id="task?invalid",
        ),
        "https://agent.example.com",
    )

    assert warning is None
    assert saved is not None
    assert saved.context_id == "ctx-valid-123"
    assert saved.task_id is None


def test_resolve_saved_conversation_rejects_invalid_context_id() -> None:
    """Invalid saved context IDs should be ignored with a warning."""
    saved, warning = resolve_saved_conversation(
        AgentSession(
            agent_url="https://agent.example.com",
            context_id="ctx?invalid",
            task_id="task-valid-123",
        ),
        "https://agent.example.com",
    )

    assert saved is None
    assert warning is not None
    assert "saved session ignored" in warning
