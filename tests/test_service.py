"""Tests for the A2A service layer module."""

import httpx
import pytest
from a2a.types import Message, Part, Role, Task, TaskState, TaskStatus, TextPart

from a2a_handler.auth import create_bearer_auth
from a2a_handler.service import (
    A2AService,
    SendResult,
    StreamEvent,
    TaskResult,
    TERMINAL_TASK_STATES,
    extract_text_from_task,
    extract_text_from_message_parts,
)


def _make_task(
    state: TaskState, task_id: str = "task-123", context_id: str = "ctx-123"
) -> Task:
    """Helper to create a Task with the given state."""
    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=state),
    )


def _make_message(context_id: str = "ctx-123", task_id: str | None = None) -> Message:
    """Helper to create a Message."""
    return Message(
        message_id="msg-123",
        role=Role.agent,
        parts=[Part(root=TextPart(text="Hello"))],
        context_id=context_id,
        task_id=task_id,
    )


class TestSendResult:
    """Tests for SendResult dataclass."""

    def test_is_complete_when_completed(self):
        """Test is_complete returns True for completed state."""
        result = SendResult(task=_make_task(TaskState.completed))
        assert result.is_complete is True

    def test_is_complete_when_canceled(self):
        """Test is_complete returns True for canceled state."""
        result = SendResult(task=_make_task(TaskState.canceled))
        assert result.is_complete is True

    def test_is_complete_when_failed(self):
        """Test is_complete returns True for failed state."""
        result = SendResult(task=_make_task(TaskState.failed))
        assert result.is_complete is True

    def test_is_complete_when_rejected(self):
        """Test is_complete returns True for rejected state."""
        result = SendResult(task=_make_task(TaskState.rejected))
        assert result.is_complete is True

    def test_is_complete_when_working(self):
        """Test is_complete returns False for working state."""
        result = SendResult(task=_make_task(TaskState.working))
        assert result.is_complete is False

    def test_is_complete_when_no_state(self):
        """Test is_complete returns False when no task or message."""
        result = SendResult()
        assert result.is_complete is False

    def test_needs_input_when_input_required(self):
        """Test needs_input returns True for input_required state."""
        result = SendResult(task=_make_task(TaskState.input_required))
        assert result.needs_input is True

    def test_needs_input_when_working(self):
        """Test needs_input returns False for working state."""
        result = SendResult(task=_make_task(TaskState.working))
        assert result.needs_input is False

    def test_needs_input_when_no_state(self):
        """Test needs_input returns False when no task or message."""
        result = SendResult()
        assert result.needs_input is False

    def test_context_id_from_task(self):
        """Test context_id is derived from task."""
        result = SendResult(task=_make_task(TaskState.completed, context_id="ctx-456"))
        assert result.context_id == "ctx-456"

    def test_context_id_from_message(self):
        """Test context_id is derived from message when no task."""
        result = SendResult(message=_make_message(context_id="ctx-789"))
        assert result.context_id == "ctx-789"

    def test_task_id_from_task(self):
        """Test task_id is derived from task."""
        result = SendResult(task=_make_task(TaskState.completed, task_id="task-456"))
        assert result.task_id == "task-456"

    def test_task_id_from_message(self):
        """Test task_id is derived from message when no task."""
        result = SendResult(message=_make_message(task_id="task-789"))
        assert result.task_id == "task-789"

    def test_state_from_task(self):
        """Test state is derived from task status."""
        result = SendResult(task=_make_task(TaskState.working))
        assert result.state == TaskState.working


class TestStreamEvent:
    """Tests for StreamEvent dataclass."""

    def test_create_message_event(self):
        """Test creating a message event with message object."""
        msg = _make_message(context_id="ctx-123", task_id="task-456")
        event = StreamEvent(
            event_type="message",
            message=msg,
            text="Hello, world!",
        )

        assert event.event_type == "message"
        assert event.context_id == "ctx-123"
        assert event.task_id == "task-456"
        assert event.text == "Hello, world!"

    def test_create_status_event(self):
        """Test creating a status event with task object."""
        task = _make_task(TaskState.working, task_id="task-456")
        event = StreamEvent(
            event_type="status",
            task=task,
        )

        assert event.event_type == "status"
        assert event.task_id == "task-456"
        assert event.state == TaskState.working

    def test_context_id_from_task(self):
        """Test context_id derived from task."""
        task = _make_task(TaskState.completed, context_id="ctx-abc")
        event = StreamEvent(event_type="task", task=task)
        assert event.context_id == "ctx-abc"


class TestTaskResult:
    """Tests for TaskResult dataclass."""

    def test_create_task_result(self):
        """Test creating a task result."""
        mock_task = _make_task(
            TaskState.completed, task_id="task-123", context_id="ctx-123"
        )

        result = TaskResult(
            task=mock_task,
            text="Task completed successfully",
        )

        assert result.task_id == "task-123"
        assert result.context_id == "ctx-123"
        assert result.state == TaskState.completed
        assert result.text == "Task completed successfully"

    def test_properties_derived_from_task(self):
        """Test that properties are correctly derived from the SDK Task object."""
        task = _make_task(TaskState.failed, task_id="task-xyz", context_id="ctx-xyz")
        result = TaskResult(task=task)

        assert result.task_id == "task-xyz"
        assert result.context_id == "ctx-xyz"
        assert result.state == TaskState.failed


class TestExtractTextFromMessageParts:
    """Tests for extract_text_from_message_parts function."""

    def test_extract_from_none(self):
        """Test extracting from None returns empty string."""
        result = extract_text_from_message_parts(None)
        assert result == ""

    def test_extract_from_empty_list(self):
        """Test extracting from empty list returns empty string."""
        result = extract_text_from_message_parts([])
        assert result == ""

    def test_extract_from_text_part_with_root(self):
        """Test extracting from TextPart wrapped in Part."""
        parts = [Part(root=TextPart(text="Hello, world!"))]
        result = extract_text_from_message_parts(parts)
        assert result == "Hello, world!"

    def test_extract_multiple_parts(self):
        """Test extracting from multiple parts joins with newlines."""
        parts = [
            Part(root=TextPart(text="First line")),
            Part(root=TextPart(text="Second line")),
        ]
        result = extract_text_from_message_parts(parts)
        assert result == "First line\nSecond line"


class TestTerminalStates:
    """Tests for terminal state constants."""

    def test_terminal_states_include_completed(self):
        """Test that completed is a terminal state."""
        assert TaskState.completed in TERMINAL_TASK_STATES

    def test_terminal_states_include_canceled(self):
        """Test that canceled is a terminal state."""
        assert TaskState.canceled in TERMINAL_TASK_STATES

    def test_terminal_states_include_failed(self):
        """Test that failed is a terminal state."""
        assert TaskState.failed in TERMINAL_TASK_STATES

    def test_terminal_states_include_rejected(self):
        """Test that rejected is a terminal state."""
        assert TaskState.rejected in TERMINAL_TASK_STATES

    def test_working_is_not_terminal(self):
        """Test that working is not a terminal state."""
        assert TaskState.working not in TERMINAL_TASK_STATES


class TestSendResultNeedsAuth:
    """Tests for SendResult.needs_auth property."""

    def test_needs_auth_when_auth_required(self):
        """Test needs_auth returns True for auth_required state."""
        result = SendResult(task=_make_task(TaskState.auth_required))
        assert result.needs_auth is True

    def test_needs_auth_when_working(self):
        """Test needs_auth returns False for working state."""
        result = SendResult(task=_make_task(TaskState.working))
        assert result.needs_auth is False

    def test_needs_auth_when_no_state(self):
        """Test needs_auth returns False when no task or message."""
        result = SendResult()
        assert result.needs_auth is False


class TestStreamEventStatusFields:
    """Additional tests for StreamEvent with TaskStatusUpdateEvent."""

    def test_context_id_from_status_event(self):
        """Test context_id derived from status update event."""
        from a2a.types import TaskStatusUpdateEvent, TaskStatus

        status_event = TaskStatusUpdateEvent(
            task_id="task-123",
            context_id="ctx-status",
            final=False,
            status=TaskStatus(state=TaskState.working),
        )
        event = StreamEvent(event_type="status", status=status_event)
        assert event.context_id == "ctx-status"

    def test_task_id_from_status_event(self):
        """Test task_id derived from status update event."""
        from a2a.types import TaskStatusUpdateEvent, TaskStatus

        status_event = TaskStatusUpdateEvent(
            task_id="task-from-status",
            context_id="ctx-123",
            final=False,
            status=TaskStatus(state=TaskState.working),
        )
        event = StreamEvent(event_type="status", status=status_event)
        assert event.task_id == "task-from-status"

    def test_state_from_status_event(self):
        """Test state derived from status update event."""
        from a2a.types import TaskStatusUpdateEvent, TaskStatus

        status_event = TaskStatusUpdateEvent(
            task_id="task-123",
            context_id="ctx-123",
            final=False,
            status=TaskStatus(state=TaskState.working),
        )
        event = StreamEvent(event_type="status", status=status_event)
        assert event.state == TaskState.working


class TestStreamEventArtifact:
    """Tests for StreamEvent with artifact events."""

    def test_context_id_from_artifact(self):
        """Test context_id derived from artifact event."""
        from a2a.types import TaskArtifactUpdateEvent, Artifact

        artifact_event = TaskArtifactUpdateEvent(
            task_id="task-123",
            context_id="ctx-artifact",
            artifact=Artifact(
                artifact_id="art-1",
                parts=[Part(root=TextPart(text="text"))],
            ),
        )
        event = StreamEvent(event_type="artifact", artifact=artifact_event)
        assert event.context_id == "ctx-artifact"

    def test_task_id_from_artifact(self):
        """Test task_id derived from artifact event."""
        from a2a.types import TaskArtifactUpdateEvent, Artifact

        artifact_event = TaskArtifactUpdateEvent(
            task_id="task-artifact",
            context_id="ctx-123",
            artifact=Artifact(
                artifact_id="art-1",
                parts=[Part(root=TextPart(text="text"))],
            ),
        )
        event = StreamEvent(event_type="artifact", artifact=artifact_event)
        assert event.task_id == "task-artifact"


class TestTaskResultState:
    """Additional tests for TaskResult state handling."""

    def test_state_default_when_unknown(self):
        """Test state returns unknown when task has unknown state."""
        task = Task(
            id="task-123",
            context_id="ctx-123",
            status=TaskStatus(state=TaskState.unknown),
        )
        result = TaskResult(task=task)
        assert result.state == TaskState.unknown


class TestExtractTextFromTask:
    """Tests for extract_text_from_task function."""

    def test_extract_from_task_with_artifacts(self):
        """Test extracting text from task artifacts."""
        from a2a_handler.service import extract_text_from_task
        from a2a.types import Artifact

        task = Task(
            id="task-123",
            context_id="ctx-123",
            status=TaskStatus(state=TaskState.completed),
            artifacts=[
                Artifact(
                    artifact_id="art-1",
                    parts=[Part(root=TextPart(text="Artifact text"))],
                )
            ],
        )

        result = extract_text_from_task(task)
        assert result == "Artifact text"

    def test_extract_from_task_with_history_no_artifacts(self):
        """Test extracting text from task history when no artifacts."""
        from a2a_handler.service import extract_text_from_task

        task = Task(
            id="task-123",
            context_id="ctx-123",
            status=TaskStatus(state=TaskState.completed),
            artifacts=[],
            history=[
                Message(
                    message_id="msg-1",
                    role=Role.agent,
                    parts=[Part(root=TextPart(text="History text"))],
                    context_id="ctx-123",
                )
            ],
        )

        result = extract_text_from_task(task)
        assert result == "History text"

    def test_extract_prefers_artifacts_over_history(self):
        """Test that artifacts take precedence over history."""
        from a2a_handler.service import extract_text_from_task
        from a2a.types import Artifact

        task = Task(
            id="task-123",
            context_id="ctx-123",
            status=TaskStatus(state=TaskState.completed),
            artifacts=[
                Artifact(
                    artifact_id="art-1",
                    parts=[Part(root=TextPart(text="Artifact text"))],
                )
            ],
            history=[
                Message(
                    message_id="msg-1",
                    role=Role.agent,
                    parts=[Part(root=TextPart(text="History text"))],
                    context_id="ctx-123",
                )
            ],
        )

        result = extract_text_from_task(task)
        assert result == "Artifact text"
        assert "History text" not in result

    def test_extract_ignores_user_messages_in_history(self):
        """Test that user messages in history are ignored."""
        from a2a_handler.service import extract_text_from_task

        task = Task(
            id="task-123",
            context_id="ctx-123",
            status=TaskStatus(state=TaskState.completed),
            artifacts=[],
            history=[
                Message(
                    message_id="msg-1",
                    role=Role.user,
                    parts=[Part(root=TextPart(text="User text"))],
                    context_id="ctx-123",
                ),
                Message(
                    message_id="msg-2",
                    role=Role.agent,
                    parts=[Part(root=TextPart(text="Agent text"))],
                    context_id="ctx-123",
                ),
            ],
        )

        result = extract_text_from_task(task)
        assert result == "Agent text"
        assert "User text" not in result

    def test_extract_from_empty_task(self):
        """Test extracting from task with no artifacts or history."""
        from a2a_handler.service import extract_text_from_task

        task = Task(
            id="task-123",
            context_id="ctx-123",
            status=TaskStatus(state=TaskState.completed),
        )

        result = extract_text_from_task(task)
        assert result == ""


class _FakeStreamingClient:
    def __init__(self, events):
        self._events = events

    async def send_message(self, _message):
        for event in self._events:
            yield event

    async def resubscribe(self, _task_id_params):
        for event in self._events:
            yield event


@pytest.mark.asyncio
class TestA2AServiceStreamingCompatibility:
    async def test_stream_handles_tuple_with_none_update(self):
        """Test stream() maps tuple events with None update to task events."""
        task = _make_task(TaskState.completed)
        fake_client = _FakeStreamingClient(events=[(task, None)])

        async with httpx.AsyncClient() as http_client:
            service = A2AService(
                http_client=http_client, agent_url="http://example.com"
            )

            async def _get_client():
                return fake_client

            service._get_or_create_client = _get_client  # type: ignore[method-assign]

            events = [event async for event in service.stream("hello")]

        assert len(events) == 1
        assert events[0].event_type == "task"
        assert events[0].task_id == task.id
        assert events[0].text == extract_text_from_task(task)

    async def test_resubscribe_handles_tuple_with_none_update(self):
        """Test resubscribe() maps tuple events with None update to task events."""
        task = _make_task(TaskState.working)
        fake_client = _FakeStreamingClient(events=[(task, None)])

        async with httpx.AsyncClient() as http_client:
            service = A2AService(
                http_client=http_client, agent_url="http://example.com"
            )

            async def _get_client():
                return fake_client

            service._get_or_create_client = _get_client  # type: ignore[method-assign]

            events = [event async for event in service.resubscribe(task.id)]

        assert len(events) == 1
        assert events[0].event_type == "task"
        assert events[0].task_id == task.id

    async def test_send_returns_task_text_for_tuple_with_none_update(self):
        """Test send() still returns task text when update payload is None."""
        task = Task(
            id="task-123",
            context_id="ctx-123",
            status=TaskStatus(state=TaskState.completed),
            history=[
                Message(
                    message_id="msg-1",
                    role=Role.agent,
                    parts=[Part(root=TextPart(text="Done"))],
                    context_id="ctx-123",
                )
            ],
        )
        fake_client = _FakeStreamingClient(events=[(task, None)])

        async with httpx.AsyncClient() as http_client:
            service = A2AService(
                http_client=http_client, agent_url="http://example.com"
            )

            async def _get_client():
                return fake_client

            service._get_or_create_client = _get_client  # type: ignore[method-assign]

            result = await service.send("hello")

        assert result.task_id == "task-123"
        assert result.state == TaskState.completed
        assert result.text == "Done"


@pytest.mark.asyncio
class TestA2AServiceAuthHeaders:
    async def test_set_credentials_applies_bearer_header_to_requests(self):
        """Test service credentials are included in outgoing HTTP requests."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("Authorization") == "Bearer test-token"
            return httpx.Response(200, json={"ok": True})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver.local"
        ) as http_client:
            service = A2AService(
                http_client=http_client, agent_url="http://example.com"
            )
            service.set_credentials(create_bearer_auth("test-token"))

            response = await http_client.get("/ping")

        assert response.status_code == 200

    async def test_clear_credentials_removes_auth_header_from_requests(self):
        """Test clearing credentials removes auth header from outgoing requests."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("Authorization") is None
            return httpx.Response(200, json={"ok": True})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver.local"
        ) as http_client:
            service = A2AService(
                http_client=http_client, agent_url="http://example.com"
            )
            service.set_credentials(create_bearer_auth("test-token"))
            service.clear_credentials()

            response = await http_client.get("/ping")

        assert response.status_code == 200
