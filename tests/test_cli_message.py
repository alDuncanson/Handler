"""Tests for CLI message commands."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner
from a2a.types import Task, TaskState, TaskStatus

from a2a_handler.cli.message import message, _format_send_result, _stream_message
from a2a_handler.common import Output
from a2a_handler.service import SendResult, StreamEvent


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


def _make_task(
    state: TaskState = TaskState.completed,
    task_id: str = "task-123",
    context_id: str = "ctx-123",
) -> Task:
    """Helper to create a Task with the given state."""
    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=state),
    )


class TestMessageSend:
    """Tests for message send command."""

    def test_message_send_success(self, runner):
        """Test successful message send."""
        mock_task = _make_task(TaskState.completed)
        mock_result = SendResult(task=mock_task, text="Response text")

        with (
            patch("a2a_handler.cli.message.build_http_client") as mock_client,
            patch("a2a_handler.cli.message.A2AService") as mock_service_cls,
            patch("a2a_handler.cli.message.update_session"),
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.send.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message, ["send", "http://localhost:8000", "Hello agent"]
            )

            assert result.exit_code == 0
            assert "Response text" in result.output

    def test_message_send_with_context_id(self, runner):
        """Test message send with context ID."""
        mock_task = _make_task(TaskState.completed)
        mock_result = SendResult(task=mock_task, text="Response")

        with (
            patch("a2a_handler.cli.message.build_http_client") as mock_client,
            patch("a2a_handler.cli.message.A2AService") as mock_service_cls,
            patch("a2a_handler.cli.message.update_session"),
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.send.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message,
                [
                    "send",
                    "http://localhost:8000",
                    "Hello",
                    "--context-id",
                    "ctx-456",
                ],
            )

            assert result.exit_code == 0
            mock_service.send.assert_called_once_with("Hello", "ctx-456", None)

    def test_message_send_with_continue_flag(self, runner):
        """Test message send with --continue flag uses session."""
        from a2a_handler.session import AgentSession

        mock_session = AgentSession(
            agent_url="http://localhost:8000",
            context_id="saved-ctx",
            task_id="saved-task",
        )
        mock_task = _make_task(TaskState.completed)
        mock_result = SendResult(task=mock_task, text="Response")

        with (
            patch("a2a_handler.cli.message.build_http_client") as mock_client,
            patch("a2a_handler.cli.message.A2AService") as mock_service_cls,
            patch("a2a_handler.cli.message.get_session", return_value=mock_session),
            patch("a2a_handler.cli.message.update_session"),
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.send.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message,
                ["send", "http://localhost:8000", "Hello", "--continue"],
            )

            assert result.exit_code == 0
            mock_service.send.assert_called_once_with("Hello", "saved-ctx", None)

    def test_message_send_with_bearer_auth(self, runner):
        """Test message send with bearer token."""
        mock_task = _make_task(TaskState.completed)
        mock_result = SendResult(task=mock_task, text="Response")

        with (
            patch("a2a_handler.cli.message.build_http_client") as mock_client,
            patch("a2a_handler.cli.message.A2AService") as mock_service_cls,
            patch("a2a_handler.cli.message.update_session"),
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.send.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message,
                [
                    "send",
                    "http://localhost:8000",
                    "Hello",
                    "--bearer",
                    "my-token",
                ],
            )

            assert result.exit_code == 0
            call_kwargs = mock_service_cls.call_args.kwargs
            assert call_kwargs["credentials"] is not None

    def test_message_send_with_push_url(self, runner):
        """Test message send with push notification URL."""
        mock_task = _make_task(TaskState.completed)
        mock_result = SendResult(task=mock_task, text="Response")

        with (
            patch("a2a_handler.cli.message.build_http_client") as mock_client,
            patch("a2a_handler.cli.message.A2AService") as mock_service_cls,
            patch("a2a_handler.cli.message.update_session"),
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.send.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message,
                [
                    "send",
                    "http://localhost:8000",
                    "Hello",
                    "--push-url",
                    "http://webhook.example.com",
                ],
            )

            assert result.exit_code == 0
            call_kwargs = mock_service_cls.call_args.kwargs
            assert call_kwargs["push_notification_url"] == "http://webhook.example.com"

    def test_message_send_connection_error(self, runner):
        """Test message send handles connection errors."""
        import httpx

        with (
            patch("a2a_handler.cli.message.build_http_client") as mock_client,
            patch("a2a_handler.cli.message.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.send.side_effect = httpx.ConnectError("Connection refused")
            mock_service_cls.return_value = mock_service

            result = runner.invoke(message, ["send", "http://localhost:8000", "Hello"])

            assert result.exit_code == 1

    def test_message_send_with_json_payload(self, runner):
        """Test message send accepts raw json payload."""
        mock_task = _make_task(TaskState.completed)
        mock_result = SendResult(task=mock_task, text="Response")

        with (
            patch("a2a_handler.cli.message.build_http_client") as mock_client,
            patch("a2a_handler.cli.message.A2AService") as mock_service_cls,
            patch("a2a_handler.cli.message.update_session"),
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.send.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message,
                [
                    "send",
                    "http://localhost:8000",
                    "--json",
                    '{"text":"Hello from json","context_id":"ctx-9"}',
                ],
            )

            assert result.exit_code == 0
            mock_service.send.assert_called_once_with("Hello from json", "ctx-9", None)

    def test_message_send_json_requires_text(self, runner):
        """Test message send fails when text is missing in both argument and json."""
        result = runner.invoke(
            message,
            ["send", "http://localhost:8000", "--json", '{"context_id":"ctx"}'],
        )

        assert result.exit_code == 1
        assert "Provide message text" in result.output


class TestMessageStream:
    """Tests for message stream command."""

    def test_message_stream_invokes_send_with_stream_flag(self, runner):
        """Test message stream command invokes send with stream=True."""
        mock_task = _make_task(TaskState.completed)

        with (
            patch("a2a_handler.cli.message.build_http_client") as mock_client,
            patch("a2a_handler.cli.message.A2AService") as mock_service_cls,
            patch("a2a_handler.cli.message.update_session"),
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            async def mock_stream(*args, **kwargs):
                yield StreamEvent(
                    event_type="artifact",
                    text="Chunk 1",
                    task=mock_task,
                )
                yield StreamEvent(
                    event_type="status",
                    task=mock_task,
                )

            mock_service = MagicMock()
            mock_service.stream = mock_stream
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message, ["stream", "http://localhost:8000", "Hello"]
            )

            assert result.exit_code == 0
            call_kwargs = mock_service_cls.call_args.kwargs
            assert call_kwargs["enable_streaming"] is True


class TestFormatSendResult:
    """Tests for _format_send_result helper."""

    def test_format_completed_result(self):
        """Test formatting a completed result with text."""
        mock_task = _make_task(TaskState.completed, context_id="ctx-123")
        result = SendResult(task=mock_task, text="Response text here")
        output = MagicMock(spec=Output)

        _format_send_result(result, output)

        output.field.assert_any_call("Context ID", "ctx-123", dim_value=True)
        output.state.assert_called_with("State", "completed")
        output.markdown.assert_called_with("Response text here")

    def test_format_auth_required_result(self):
        """Test formatting an auth_required result."""
        mock_task = _make_task(TaskState.auth_required)
        result = SendResult(task=mock_task)
        output = MagicMock(spec=Output)

        _format_send_result(result, output)

        output.warning.assert_called_with("Authentication required")

    def test_format_no_text_result(self):
        """Test formatting a result without text."""
        mock_task = _make_task(TaskState.completed)
        result = SendResult(task=mock_task, text="")
        output = MagicMock(spec=Output)

        _format_send_result(result, output)

        output.dim.assert_called_with("No text content in response")


class TestStreamMessage:
    """Tests for _stream_message helper."""

    @pytest.mark.asyncio
    async def test_stream_message_collects_text(self):
        """Test _stream_message collects and outputs text."""
        mock_task = _make_task(TaskState.completed)

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(
                event_type="artifact",
                text="First chunk",
                task=mock_task,
            )
            yield StreamEvent(
                event_type="artifact",
                text="Second chunk",
                task=mock_task,
            )

        mock_service = MagicMock()
        mock_service.stream = mock_stream

        output = MagicMock(spec=Output)

        with patch("a2a_handler.cli.message.update_session"):
            await _stream_message(
                mock_service,
                "Hello",
                None,
                None,
                "http://localhost:8000",
                output,
            )

        assert output.line.call_count == 2

    @pytest.mark.asyncio
    async def test_stream_message_shows_auth_warning(self):
        """Test _stream_message shows auth warning when needed."""
        mock_task = _make_task(TaskState.auth_required)

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(
                event_type="status",
                task=mock_task,
            )

        mock_service = MagicMock()
        mock_service.stream = mock_stream

        output = MagicMock(spec=Output)

        with patch("a2a_handler.cli.message.update_session"):
            await _stream_message(
                mock_service,
                "Hello",
                None,
                None,
                "http://localhost:8000",
                output,
            )

        output.warning.assert_called_with("Authentication required")
