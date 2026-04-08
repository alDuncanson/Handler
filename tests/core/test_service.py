"""Tests for the A2A service layer module."""

from unittest.mock import AsyncMock

import httpx
import pytest
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    Message,
    Part,
    PushNotificationConfig,
    Role,
    Task,
    TaskPushNotificationConfig,
    TaskState,
    TaskStatus,
    TextPart,
)
from typing import cast

from a2a_handler.auth import create_bearer_auth, create_oauth2_auth
from a2a_handler.common.input_validation import InputValidationError
from a2a_handler.service import (
    A2AService,
    StreamEvent,
    TERMINAL_TASK_STATES,
    extract_text,
    extract_text_from_task,
    extract_text_from_message_parts,
    is_terminal,
    protocol_dump,
    response_context_id,
    response_needs_auth,
    response_state,
    response_task_id,
)
from a2a_handler.service import (
    AGENT_CARD_WELL_KNOWN_PATH,
    PREV_AGENT_CARD_WELL_KNOWN_PATH,
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


class TestResponseHelpers:
    """Tests for A2AResponse helper functions."""

    def test_is_terminal_when_completed(self):
        assert is_terminal(_make_task(TaskState.completed)) is True

    def test_is_terminal_when_canceled(self):
        assert is_terminal(_make_task(TaskState.canceled)) is True

    def test_is_terminal_when_failed(self):
        assert is_terminal(_make_task(TaskState.failed)) is True

    def test_is_terminal_when_rejected(self):
        assert is_terminal(_make_task(TaskState.rejected)) is True

    def test_is_terminal_when_working(self):
        assert is_terminal(_make_task(TaskState.working)) is False

    def test_is_terminal_for_message(self):
        assert is_terminal(_make_message()) is False

    def test_needs_auth_when_auth_required(self):
        assert response_needs_auth(_make_task(TaskState.auth_required)) is True

    def test_needs_auth_when_working(self):
        assert response_needs_auth(_make_task(TaskState.working)) is False

    def test_needs_auth_for_message(self):
        assert response_needs_auth(_make_message()) is False

    def test_context_id_from_task(self):
        assert (
            response_context_id(_make_task(TaskState.completed, context_id="ctx-456"))
            == "ctx-456"
        )

    def test_context_id_from_message(self):
        assert response_context_id(_make_message(context_id="ctx-789")) == "ctx-789"

    def test_task_id_from_task(self):
        assert (
            response_task_id(_make_task(TaskState.completed, task_id="task-456"))
            == "task-456"
        )

    def test_task_id_from_message(self):
        assert response_task_id(_make_message(task_id="task-789")) == "task-789"

    def test_state_from_task(self):
        assert response_state(_make_task(TaskState.working)) == TaskState.working

    def test_state_from_message(self):
        assert response_state(_make_message()) is None

    def test_extract_text_from_task(self):
        task = Task(
            id="t",
            context_id="c",
            status=TaskStatus(state=TaskState.completed),
            history=[
                Message(
                    message_id="m",
                    role=Role.agent,
                    parts=[Part(root=TextPart(text="Hello"))],
                    context_id="c",
                )
            ],
        )
        assert extract_text(task) == "Hello"

    def test_extract_text_from_message(self):
        msg = _make_message()
        assert extract_text(msg) == "Hello"

    def test_protocol_dump_task(self):
        task = _make_task(TaskState.completed)
        dumped = protocol_dump(task)
        assert dumped["id"] == "task-123"
        status = dumped["status"]
        assert isinstance(status, dict)
        typed_status = cast(dict[str, object], status)
        assert typed_status["state"] == "completed"
        assert "kind" in dumped

    def test_protocol_dump_message(self):
        msg = _make_message()
        dumped = protocol_dump(msg)
        assert dumped["contextId"] == "ctx-123"
        assert dumped["role"] == "agent"


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


class _FakePushConfigClient:
    def __init__(self) -> None:
        self.push_config = None

    async def set_task_callback(self, push_config):
        self.push_config = push_config
        return push_config


class _FakeGetPushConfigClient:
    def __init__(self, result: TaskPushNotificationConfig) -> None:
        self.result = result
        self.params = None

    async def get_task_callback(self, params):
        self.params = params
        return self.result


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

        assert isinstance(result, Task)
        assert result.id == "task-123"
        assert result.status.state == TaskState.completed
        assert extract_text(result) == "Done"


@pytest.mark.asyncio
class TestA2AServicePushConfigValidation:
    async def test_init_rejects_invalid_push_notification_url(self) -> None:
        """Service constructor validates optional push notification defaults."""
        async with httpx.AsyncClient() as http_client:
            with pytest.raises(InputValidationError) as error:
                A2AService(
                    http_client=http_client,
                    agent_url="http://example.com",
                    push_notification_url="not-a-url",
                )

        assert isinstance(error.value, InputValidationError)
        assert error.value.code == "invalid_webhook_url"

    async def test_set_push_config_rejects_invalid_webhook_url(self) -> None:
        """Service rejects malformed webhook URLs before sending requests."""
        async with httpx.AsyncClient() as http_client:
            service = A2AService(
                http_client=http_client, agent_url="http://example.com"
            )

            with pytest.raises(InputValidationError) as error:
                await service.set_push_config("task-123", "not-a-url")

        assert isinstance(error.value, InputValidationError)
        assert error.value.code == "invalid_webhook_url"

    async def test_set_push_config_passes_valid_values_to_client(self) -> None:
        """Service keeps passing valid callback configs to the SDK client."""
        fake_client = _FakePushConfigClient()

        async with httpx.AsyncClient() as http_client:
            service = A2AService(
                http_client=http_client, agent_url="http://example.com"
            )

            async def _get_client():
                return fake_client

            service._get_or_create_client = _get_client  # type: ignore[method-assign]

            result = await service.set_push_config(
                "task-123",
                "https://example.com/webhook",
                "token-123",
            )

        assert result.task_id == "task-123"
        assert result.push_notification_config is not None
        assert result.push_notification_config.url == "https://example.com/webhook"
        assert fake_client.push_config is not None


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


@pytest.mark.asyncio
class TestA2AServiceOAuthAndCards:
    async def test_ensure_oauth2_token_fetches_and_applies_new_header(self) -> None:
        """Refreshing OAuth2 credentials should update headers and invalidate the SDK client."""
        credentials = create_oauth2_auth(
            "https://auth.example.com/token",
            "client-id",
            "client-secret",
        )

        async with httpx.AsyncClient() as http_client:
            service = A2AService(
                http_client=http_client,
                agent_url="http://example.com",
                credentials=credentials,
            )
            service._cached_client = object()  # type: ignore[assignment]

            async def _fetch_token() -> str:
                credentials.value = "oauth-access-token"
                return credentials.value

            credentials.fetch_oauth2_token = _fetch_token  # type: ignore[method-assign]

            await service.ensure_oauth2_token()

        assert http_client.headers["Authorization"] == "Bearer oauth-access-token"
        assert service._applied_auth_headers == {"Authorization"}
        assert service._cached_client is None

    async def test_ensure_oauth2_token_skips_fetch_when_token_is_still_valid(
        self,
    ) -> None:
        """A valid cached OAuth token should not be fetched again."""
        credentials = create_oauth2_auth(
            "https://auth.example.com/token",
            "client-id",
            "client-secret",
            access_token="cached-token",
        )
        credentials._token_expires_at = float("inf")

        async with httpx.AsyncClient() as http_client:
            service = A2AService(
                http_client=http_client,
                agent_url="http://example.com",
                credentials=credentials,
            )
            cached_client = object()
            service._cached_client = cached_client  # type: ignore[assignment]
            fetch_token = AsyncMock()
            credentials.fetch_oauth2_token = fetch_token  # type: ignore[method-assign]

            await service.ensure_oauth2_token()

        fetch_token.assert_not_awaited()
        assert service._cached_client is cached_client
        assert http_client.headers["Authorization"] == "Bearer cached-token"

    async def test_get_or_create_client_fetches_unknown_expiry_token_once(
        self, monkeypatch
    ) -> None:
        """Unknown-expiry OAuth2 tokens should refresh once per client creation."""
        credentials = create_oauth2_auth(
            "https://auth.example.com/token",
            "client-id",
            "client-secret",
        )
        card = AgentCard(
            name="OAuth Agent",
            description="Test agent",
            url="http://example.com",
            version="1.0.0",
            default_input_modes=["text"],
            default_output_modes=["text"],
            capabilities=AgentCapabilities(streaming=True, push_notifications=False),
            skills=[],
        )
        fetch_count = 0

        async def _fetch_token() -> str:
            nonlocal fetch_count
            fetch_count += 1
            credentials.value = f"oauth-token-{fetch_count}"
            credentials._token_expires_at = None
            return credentials.value

        class _Resolver:
            def __init__(self, _http_client, _agent_url, agent_card_path=None) -> None:
                self.agent_card_path = agent_card_path

            async def get_agent_card(self):
                return card

        class _Factory:
            def __init__(self, _config) -> None:
                pass

            def create(self, _card):
                return object()

        credentials.fetch_oauth2_token = _fetch_token  # type: ignore[method-assign]
        monkeypatch.setattr("a2a_handler.service.A2ACardResolver", _Resolver)
        monkeypatch.setattr("a2a_handler.service.ClientFactory", _Factory)

        async with httpx.AsyncClient() as http_client:
            service = A2AService(
                http_client=http_client,
                agent_url="http://example.com",
                credentials=credentials,
            )

            await service._get_or_create_client()

        assert fetch_count == 1
        assert http_client.headers["Authorization"] == "Bearer oauth-token-1"

    async def test_get_card_falls_back_to_previous_well_known_path(
        self, monkeypatch
    ) -> None:
        """Older agents served at the legacy card path should still resolve successfully."""
        card = AgentCard(
            name="Fallback Agent",
            description="Legacy card path",
            url="http://example.com",
            version="1.0.0",
            default_input_modes=["text"],
            default_output_modes=["text"],
            capabilities=AgentCapabilities(streaming=True, push_notifications=True),
            skills=[],
        )
        seen_paths: list[str] = []

        class _Resolver:
            def __init__(self, _http_client, _agent_url, agent_card_path=None) -> None:
                self.agent_card_path = agent_card_path or AGENT_CARD_WELL_KNOWN_PATH
                seen_paths.append(self.agent_card_path)

            async def get_agent_card(self):
                if self.agent_card_path == AGENT_CARD_WELL_KNOWN_PATH:
                    raise httpx.HTTPStatusError(
                        "missing",
                        request=httpx.Request(
                            "GET", "http://example.com/.well-known/agent-card.json"
                        ),
                        response=httpx.Response(404),
                    )
                return card

        monkeypatch.setattr("a2a_handler.service.A2ACardResolver", _Resolver)

        async with httpx.AsyncClient() as http_client:
            service = A2AService(
                http_client=http_client, agent_url="http://example.com"
            )

            first = await service.get_card()
            second = await service.get_card()

        assert first is card
        assert second is card
        assert seen_paths == [
            AGENT_CARD_WELL_KNOWN_PATH,
            PREV_AGENT_CARD_WELL_KNOWN_PATH,
        ]
        assert service.supports_streaming is True
        assert service.supports_push_notifications is True

    async def test_get_push_config_passes_task_and_config_id_to_client(self) -> None:
        """Push config lookup should preserve both the task ID and optional config ID."""
        expected = TaskPushNotificationConfig(
            task_id="task-123",
            push_notification_config=PushNotificationConfig(
                url="https://example.com/webhook",
                token="token-123",
            ),
        )
        fake_client = _FakeGetPushConfigClient(expected)

        async with httpx.AsyncClient() as http_client:
            service = A2AService(
                http_client=http_client,
                agent_url="http://example.com",
            )

            async def _get_client():
                return fake_client

            service._get_or_create_client = _get_client  # type: ignore[method-assign]

            result = await service.get_push_config(
                "task-123",
                config_id="config-456",
            )

        assert result == expected
        assert fake_client.params is not None
        assert fake_client.params.id == "task-123"
        assert fake_client.params.push_notification_config_id == "config-456"

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
