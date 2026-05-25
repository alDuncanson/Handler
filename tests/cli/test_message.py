"""Tests for CLI message commands."""

import os
from unittest.mock import AsyncMock, MagicMock, patch
from unittest.mock import patch as mock_patch

import pytest
from click.testing import CliRunner
from a2a.types import (
    DataPart,
    FilePart,
    FileWithBytes,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

from a2a_handler.cli.message import message, _format_response, _stream_message
from a2a_handler.common import Output
from a2a_handler.service import StreamEvent


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


def _make_task(
    state: TaskState = TaskState.completed,
    task_id: str = "task-123",
    context_id: str = "ctx-123",
    text: str | None = None,
) -> Task:
    """Helper to create a Task with the given state."""
    history = None
    if text:
        history = [
            Message(
                message_id="msg-1",
                role=Role.agent,
                parts=[Part(root=TextPart(text=text))],
                context_id=context_id,
            )
        ]
    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=state),
        history=history,
    )


class TestMessageSend:
    """Tests for message send command."""

    def test_message_send_success(self, runner):
        """Test successful message send."""
        mock_task = _make_task(TaskState.completed, text="Response text")

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
            mock_service.send.return_value = mock_task
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message,
                ["send", "--url", "http://localhost:8000", "--text", "Hello agent"],
            )

            assert result.exit_code == 0
            assert "Response text" in result.output

    def test_message_send_with_context_id(self, runner):
        """Test message send with context ID."""
        mock_task = _make_task(TaskState.completed, text="Response")

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
            mock_service.send.return_value = mock_task
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message,
                [
                    "send",
                    "--url",
                    "http://localhost:8000",
                    "--text",
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
        mock_task = _make_task(TaskState.completed, text="Response")

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
            mock_service.send.return_value = mock_task
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message,
                [
                    "send",
                    "--url",
                    "http://localhost:8000",
                    "--text",
                    "Hello",
                    "--continue",
                ],
            )

            assert result.exit_code == 0
            mock_service.send.assert_called_once_with(
                "Hello", "saved-ctx", "saved-task"
            )

    def test_message_send_with_bearer_auth(self, runner):
        """Test message send with bearer token."""
        mock_task = _make_task(TaskState.completed, text="Response")

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
            mock_service.send.return_value = mock_task
            mock_service_cls.return_value = mock_service

            with mock_patch.dict(os.environ, {"TEST_BEARER": "my-token"}):
                result = runner.invoke(
                    message,
                    [
                        "send",
                        "--url",
                        "http://localhost:8000",
                        "--text",
                        "Hello",
                        "--bearer-env",
                        "TEST_BEARER",
                    ],
                )

            assert result.exit_code == 0
            call_kwargs = mock_service_cls.call_args.kwargs
            assert call_kwargs["credentials"] is not None

    def test_message_send_with_push_url(self, runner):
        """Test message send with push notification URL."""
        mock_task = _make_task(TaskState.completed, text="Response")

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
            mock_service.send.return_value = mock_task
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message,
                [
                    "send",
                    "--url",
                    "http://localhost:8000",
                    "--text",
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

            result = runner.invoke(
                message,
                ["send", "--url", "http://localhost:8000", "--text", "Hello"],
            )

            assert result.exit_code == 1

    def test_message_send_with_json_payload(self, runner):
        """Test message send accepts raw json payload."""
        mock_task = _make_task(TaskState.completed, text="Response")

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
            mock_service.send.return_value = mock_task
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                message,
                [
                    "send",
                    "--url",
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
            [
                "send",
                "--url",
                "http://localhost:8000",
                "--json",
                '{"context_id":"ctx"}',
            ],
        )

        assert result.exit_code == 1
        assert "Provide message text" in result.output

    def test_message_send_rejects_invalid_agent_url(self, runner):
        """Test message send rejects invalid agent URLs."""
        result = runner.invoke(
            message, ["send", "--url", "not-a-url", "--text", "Hello"]
        )

        assert result.exit_code == 1
        assert "agent_url must be a valid http(s) URL" in result.output

    def test_message_send_requires_url_or_server(self, runner):
        """Test message send fails without --url or --server."""
        result = runner.invoke(message, ["send", "--text", "Hello"])

        assert result.exit_code != 0
        assert "Provide --url or --server" in result.output


class TestMessageStream:
    """Tests for message stream command."""

    def test_message_stream_invokes_send_with_stream_flag(self, runner):
        """Test message stream command invokes send with stream=True."""
        mock_task = _make_task(TaskState.completed)

        with (
            patch("a2a_handler.cli.message.build_streaming_http_client") as mock_client,
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
                message,
                ["stream", "--url", "http://localhost:8000", "--text", "Hello"],
            )

            assert result.exit_code == 0
            call_kwargs = mock_service_cls.call_args.kwargs
            assert call_kwargs["enable_streaming"] is True


class TestFormatResponse:
    """Tests for _format_response helper."""

    def test_format_completed_result(self):
        """Test formatting a completed result with text."""
        mock_task = _make_task(
            TaskState.completed, context_id="ctx-123", text="Response text here"
        )
        output = MagicMock(spec=Output)

        _format_response(mock_task, output)

        call_data = output.json.call_args[0][0]
        assert call_data["contextId"] == "ctx-123"
        assert call_data["status"]["state"] == "completed"

    def test_format_auth_required_result(self):
        """Test formatting an auth_required result."""
        mock_task = _make_task(TaskState.auth_required)
        output = MagicMock(spec=Output)

        _format_response(mock_task, output)

        call_data = output.json.call_args[0][0]
        assert call_data["status"]["state"] == "auth-required"

    def test_format_no_text_result(self):
        """Test formatting a result without text."""
        mock_task = _make_task(TaskState.completed)
        output = MagicMock(spec=Output)
        output.is_structured = True

        _format_response(mock_task, output)

        output.json.assert_called_once()

    def test_format_data_and_file_parts_as_readable_text(self):
        """Test text mode formats non-text parts without raw protocol reprs."""
        mock_message = Message(
            message_id="msg-1",
            role=Role.agent,
            parts=[
                Part(root=TextPart(text="Here is data:")),
                Part(root=DataPart(data={"answer": 42})),
                Part(
                    root=FilePart(
                        file=FileWithBytes(
                            bytes="YWJj",
                            name="example.txt",
                            mime_type="text/plain",
                        )
                    )
                ),
            ],
        )
        output = MagicMock(spec=Output)
        output.is_structured = False

        _format_response(mock_message, output)

        text = output.text.call_args.args[0]
        assert "Here is data:" in text
        assert '"answer": 42' in text
        assert "[file: example.txt, text/plain, inline bytes" in text


class TestStreamMessage:
    """Tests for _stream_message helper."""

    @pytest.mark.asyncio
    async def test_stream_message_collects_response(self):
        """Test _stream_message emits JSON for last response in JSON mode."""
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
        output.output_format = "json"

        with patch("a2a_handler.cli.message.update_session"):
            await _stream_message(
                mock_service,
                "Hello",
                None,
                None,
                "http://localhost:8000",
                output,
            )

        output.json.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_message_prints_text_chunks(self):
        """Test _stream_message streams text chunks in default text mode."""
        mock_task = _make_task(TaskState.completed)
        user_message = Message(
            message_id="user-msg",
            role=Role.user,
            parts=[Part(root=TextPart(text="Echoed user prompt"))],
        )

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(
                event_type="message",
                text="Echoed user prompt",
                message=user_message,
            )
            yield StreamEvent(
                event_type="artifact",
                text="First chunk ",
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
        output.output_format = "text"

        with patch("a2a_handler.cli.message.update_session"):
            await _stream_message(
                mock_service,
                "Hello",
                None,
                None,
                "http://localhost:8000",
                output,
            )

        output.text.assert_any_call("First chunk ", end="", flush=True)
        output.text.assert_any_call("Second chunk", end="", flush=True)
        assert all(
            call.args != ("Echoed user prompt",) for call in output.text.call_args_list
        )

    @pytest.mark.asyncio
    async def test_stream_message_prints_event_summaries_before_text(self):
        """Test text streams include task/tool summaries before response text."""
        task_id = "task-1234567890abcdef"
        mock_task = _make_task(TaskState.working, task_id=task_id)
        tool_call = Message(
            message_id="tool-call-msg",
            role=Role.agent,
            parts=[
                Part(
                    root=DataPart(
                        data={
                            "id": "call-1",
                            "name": "search_a2a_protocol_docs",
                            "args": {"query": "streaming"},
                        }
                    )
                )
            ],
        )
        answer = Message(
            message_id="answer-msg",
            role=Role.agent,
            parts=[Part(root=TextPart(text="A2A supports streaming updates."))],
        )

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(
                event_type="status",
                task=mock_task,
                status=TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id="ctx-123",
                    final=False,
                    status=TaskStatus(state=TaskState.working, message=tool_call),
                ),
            )
            yield StreamEvent(
                event_type="status",
                task=mock_task,
                status=TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id="ctx-123",
                    final=False,
                    status=TaskStatus(state=TaskState.working, message=answer),
                ),
            )

        mock_service = MagicMock()
        mock_service.stream = mock_stream

        output = MagicMock(spec=Output)
        output.output_format = "text"

        with patch("a2a_handler.cli.message.update_session"):
            await _stream_message(
                mock_service,
                "Hello",
                None,
                None,
                "http://localhost:8000",
                output,
            )

        calls = output.text.call_args_list
        assert calls[0].args == (f"task id: {task_id}",)
        assert calls[1].args == ("event: task working (task-123)",)
        assert calls[2].args == (
            "event: tool call search_a2a_protocol_docs (task-123)",
        )
        assert calls[3].args == ("event: message text (task-123)",)
        assert calls[4].args == ()
        assert calls[4].kwargs == {"flush": True}
        assert calls[5].args == ("A2A supports streaming updates.",)
        assert calls[5].kwargs == {"end": "", "flush": True}

    @pytest.mark.asyncio
    async def test_stream_message_auth_required(self):
        """Test _stream_message emits JSON for auth-required response."""
        mock_task = _make_task(TaskState.auth_required)

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(
                event_type="status",
                task=mock_task,
            )

        mock_service = MagicMock()
        mock_service.stream = mock_stream

        output = MagicMock(spec=Output)
        output.output_format = "json"

        with patch("a2a_handler.cli.message.update_session"):
            await _stream_message(
                mock_service,
                "Hello",
                None,
                None,
                "http://localhost:8000",
                output,
            )

        call_data = output.json.call_args[0][0]
        assert call_data["status"]["state"] == "auth-required"

    @pytest.mark.asyncio
    async def test_stream_message_emits_ndjson_events(self):
        """Test _stream_message emits each event in NDJSON mode."""
        mock_task = _make_task(TaskState.completed)

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(
                event_type="artifact",
                text="Chunk",
                task=mock_task,
            )

        mock_service = MagicMock()
        mock_service.stream = mock_stream

        output = MagicMock(spec=Output)
        output.output_format = "ndjson"

        with patch("a2a_handler.cli.message.update_session"):
            await _stream_message(
                mock_service,
                "Hello",
                None,
                None,
                "http://localhost:8000",
                output,
            )

        call_data = output.json.call_args[0][0]
        assert call_data["type"] == "artifact"
        assert call_data["text"] == "Chunk"

    @pytest.mark.asyncio
    async def test_stream_message_no_response(self):
        """Test _stream_message emits error when no response received."""

        async def mock_stream(*args, **kwargs):
            return
            yield  # make it an async generator

        mock_service = MagicMock()
        mock_service.stream = mock_stream

        output = MagicMock(spec=Output)
        output.output_format = "text"

        with patch("a2a_handler.cli.message.update_session"):
            await _stream_message(
                mock_service,
                "Hello",
                None,
                None,
                "http://localhost:8000",
                output,
            )

        output.error.assert_called_once()
