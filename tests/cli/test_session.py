"""Tests for CLI session commands."""

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from a2a_handler.cli.session import session
from a2a_handler.session import AgentSession, SessionStore


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


class TestSessionList:
    """Tests for session list command."""

    def test_list_no_sessions(self, runner):
        """Test listing when no sessions exist."""
        mock_store = MagicMock(spec=SessionStore)
        mock_store.list_all.return_value = []

        with patch(
            "a2a_handler.cli.session.get_session_store", return_value=mock_store
        ):
            result = runner.invoke(session, ["list"])

            assert result.exit_code == 0

    def test_list_with_sessions(self, runner):
        """Test listing existing sessions."""
        mock_store = MagicMock(spec=SessionStore)
        mock_store.list_all.return_value = [
            AgentSession(
                agent_url="http://localhost:8000",
                context_id="ctx-123",
                task_id="task-456",
            ),
            AgentSession(
                agent_url="http://localhost:9000",
                context_id="ctx-789",
            ),
        ]

        with patch(
            "a2a_handler.cli.session.get_session_store", return_value=mock_store
        ):
            result = runner.invoke(session, ["list"])

            assert result.exit_code == 0
            assert "localhost:8000" in result.output
            assert "localhost:9000" in result.output
            assert "ctx-123" in result.output
            assert "task-456" in result.output


class TestSessionShow:
    """Tests for session show command."""

    def test_show_session_with_ids(self, runner):
        """Test showing a session with context and task IDs."""
        mock_session = AgentSession(
            agent_url="http://localhost:8000",
            context_id="ctx-123",
            task_id="task-456",
        )

        with patch("a2a_handler.cli.session.get_session", return_value=mock_session):
            result = runner.invoke(session, ["show", "--url", "http://localhost:8000"])

            assert result.exit_code == 0
            assert "ctx-123" in result.output
            assert "task-456" in result.output

    def test_show_session_without_ids(self, runner):
        """Test showing a session without saved IDs."""
        mock_session = AgentSession(
            agent_url="http://localhost:8000",
            context_id=None,
            task_id=None,
        )

        with patch("a2a_handler.cli.session.get_session", return_value=mock_session):
            result = runner.invoke(session, ["show", "--url", "http://localhost:8000"])

            assert result.exit_code == 0
            assert "null" in result.output.lower()

    def test_show_rejects_invalid_agent_url(self, runner):
        """Test show rejects malformed agent URL."""
        result = runner.invoke(session, ["show", "--url", "not-a-url"])

        assert result.exit_code == 1
        assert "agent_url must be a valid http(s) URL" in result.output


class TestSessionClear:
    """Tests for session clear command."""

    def test_clear_specific_session(self, runner):
        """Test clearing a specific session."""
        with patch("a2a_handler.cli.session.clear_session") as mock_clear:
            result = runner.invoke(session, ["clear", "--url", "http://localhost:8000"])

            assert result.exit_code == 0
            assert '"cleared"' in result.output
            mock_clear.assert_called_once_with("http://localhost:8000")

    def test_clear_all_sessions(self, runner):
        """Test clearing all sessions with --all flag."""
        with patch("a2a_handler.cli.session.clear_session") as mock_clear:
            result = runner.invoke(session, ["clear", "--all"])

            assert result.exit_code == 0
            assert '"cleared": "all"' in result.output
            mock_clear.assert_called_once_with()

    def test_clear_without_args_shows_error(self, runner):
        """Test clearing without args shows error."""
        result = runner.invoke(session, ["clear"])

        assert result.exit_code == 0
        assert "Provide --url or --server" in result.output

    def test_clear_rejects_invalid_agent_url(self, runner):
        """Test clearing a malformed URL fails with validation error."""
        result = runner.invoke(session, ["clear", "--url", "not-a-url"])

        assert result.exit_code == 1
        assert "agent_url must be a valid http(s) URL" in result.output
