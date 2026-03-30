"""Tests for task CLI commands."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from click.testing import CliRunner
from a2a.types import Task, TaskState, TaskStatus, PushNotificationConfig

from a2a_handler.cli.task import task
from a2a_handler.service import TaskResult, StreamEvent


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


class TestTaskGet:
    """Tests for task get command."""

    def test_task_get_success(self, runner):
        """Test successful task get command."""
        mock_task = _make_task(TaskState.completed)
        mock_result = TaskResult(task=mock_task, text="Task output text")

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "get",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                ],
            )

            assert result.exit_code == 0
            assert "task-123" in result.output

    def test_task_get_with_history_length(self, runner):
        """Test task get with history length option."""
        mock_task = _make_task(TaskState.completed)
        mock_result = TaskResult(task=mock_task)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "get",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                    "-n",
                    "5",
                ],
            )

            assert result.exit_code == 0
            mock_service.get_task.assert_called_once_with("task-123", 5)

    def test_task_get_with_bearer_auth(self, runner):
        """Test task get with bearer token override."""
        mock_task = _make_task(TaskState.completed)
        mock_result = TaskResult(task=mock_task)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "get",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                    "--bearer",
                    "my-token",
                ],
            )

            assert result.exit_code == 0
            # Verify the service was created with credentials
            call_kwargs = mock_service_cls.call_args.kwargs
            assert call_kwargs["credentials"] is not None

    def test_task_get_with_api_key_auth(self, runner):
        """Test task get with API key override."""
        mock_task = _make_task(TaskState.completed)
        mock_result = TaskResult(task=mock_task)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "get",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                    "--api-key",
                    "my-key",
                ],
            )

            assert result.exit_code == 0

    def test_task_get_connection_error(self, runner):
        """Test task get handles connection errors gracefully."""
        import httpx

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.side_effect = httpx.ConnectError("Connection refused")
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "get",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                ],
            )

            assert result.exit_code == 1
            assert "Connection refused" in result.output

    def test_task_get_with_json_params(self, runner):
        """Test task get supports raw json params."""
        mock_task = _make_task(TaskState.completed)
        mock_result = TaskResult(task=mock_task)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "get",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                    "--params",
                    '{"task_id":"task-999","history_length":3}',
                ],
            )

            assert result.exit_code == 0
            mock_service.get_task.assert_called_once_with("task-999", 3)

    def test_task_get_rejects_invalid_task_id(self, runner):
        """Test task get rejects malformed task IDs."""
        result = runner.invoke(
            task,
            [
                "get",
                "--url",
                "http://localhost:8000",
                "--task",
                "task-123?fields=name",
            ],
        )

        assert result.exit_code == 1
        assert "task_id contains reserved URL characters" in result.output


class TestTaskCancel:
    """Tests for task cancel command."""

    def test_task_cancel_success(self, runner):
        """Test successful task cancel command."""
        mock_task = _make_task(TaskState.canceled)
        mock_result = TaskResult(task=mock_task)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.cancel_task.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "cancel",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                ],
            )

            assert result.exit_code == 0
            assert "canceled" in result.output.lower()

    def test_task_cancel_with_bearer(self, runner):
        """Test task cancel with bearer token."""
        mock_task = _make_task(TaskState.canceled)
        mock_result = TaskResult(task=mock_task)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.cancel_task.return_value = mock_result
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "cancel",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                    "--bearer",
                    "token",
                ],
            )

            assert result.exit_code == 0


class TestTaskResubscribe:
    """Tests for task resubscribe command."""

    def test_task_resubscribe_streams_events(self, runner):
        """Test task resubscribe yields stream events."""
        mock_task = _make_task(TaskState.working)

        async def mock_resubscribe(*args, **kwargs):
            yield StreamEvent(
                event_type="status",
                task=mock_task,
            )
            yield StreamEvent(
                event_type="artifact",
                text="Some output text",
            )

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = MagicMock()
            mock_service.resubscribe = mock_resubscribe
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "resubscribe",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                ],
            )

            assert result.exit_code == 0

    def test_task_resubscribe_with_api_key(self, runner):
        """Test task resubscribe with API key."""
        mock_task = _make_task(TaskState.completed)

        async def mock_resubscribe(*args, **kwargs):
            yield StreamEvent(event_type="status", task=mock_task)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = MagicMock()
            mock_service.resubscribe = mock_resubscribe
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "resubscribe",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                    "--api-key",
                    "my-key",
                ],
            )

            assert result.exit_code == 0


class TestTaskNotificationSet:
    """Tests for task notification set command."""

    def test_notification_set_success(self, runner):
        """Test successful notification set command."""
        from a2a.types import TaskPushNotificationConfig

        mock_config = TaskPushNotificationConfig(
            task_id="task-123",
            push_notification_config=PushNotificationConfig(
                url="http://webhook.example.com",
                token="secret-token",
            ),
        )

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.set_push_config.return_value = mock_config
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "notification",
                    "set",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                    "--webhook-url",
                    "http://webhook.example.com",
                ],
            )

            assert result.exit_code == 0
            assert "Push notification config set" in result.output

    def test_notification_set_with_token(self, runner):
        """Test notification set with authentication token."""
        from a2a.types import TaskPushNotificationConfig

        mock_config = TaskPushNotificationConfig(
            task_id="task-123",
            push_notification_config=PushNotificationConfig(
                url="http://webhook.example.com",
                token="webhook-token",
            ),
        )

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.set_push_config.return_value = mock_config
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "notification",
                    "set",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                    "--webhook-url",
                    "http://webhook.example.com",
                    "--token",
                    "webhook-token",
                ],
            )

            assert result.exit_code == 0
            mock_service.set_push_config.assert_called_once_with(
                "task-123", "http://webhook.example.com", "webhook-token"
            )

    def test_notification_set_requires_webhook_url(self, runner):
        """Test that notification set requires --webhook-url."""
        result = runner.invoke(
            task,
            [
                "notification",
                "set",
                "--url",
                "http://localhost:8000",
                "--task",
                "task-123",
            ],
        )

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()


class TestTaskNotificationGet:
    """Tests for task notification get command."""

    def test_notification_get_success(self, runner):
        """Test successful notification get command."""
        from a2a.types import TaskPushNotificationConfig

        mock_config = TaskPushNotificationConfig(
            task_id="task-123",
            push_notification_config=PushNotificationConfig(
                url="http://webhook.example.com",
                token="secret-token",
                id="config-id-123",
            ),
        )

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_push_config.return_value = mock_config
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "notification",
                    "get",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                ],
            )

            assert result.exit_code == 0
            assert "task-123" in result.output
            assert "http://webhook.example.com" in result.output

    def test_notification_get_with_config_id(self, runner):
        """Test notification get with specific config ID."""
        from a2a.types import TaskPushNotificationConfig

        mock_config = TaskPushNotificationConfig(
            task_id="task-123",
            push_notification_config=PushNotificationConfig(
                url="http://webhook.example.com",
                id="specific-config-id",
            ),
        )

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_push_config.return_value = mock_config
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "notification",
                    "get",
                    "--url",
                    "http://localhost:8000",
                    "--task",
                    "task-123",
                    "--config-id",
                    "specific-config-id",
                ],
            )

            assert result.exit_code == 0
            mock_service.get_push_config.assert_called_once_with(
                "task-123", "specific-config-id"
            )


class TestFormatTaskResult:
    """Tests for _format_task_result helper."""

    def test_format_task_result_completed(self):
        """Test formatting a completed task result."""
        from a2a_handler.cli.task import _format_task_result
        from a2a_handler.common import Output
        from unittest.mock import MagicMock

        mock_task = _make_task(TaskState.completed, context_id="ctx-abc")
        result = TaskResult(task=mock_task, text="Output text here")

        output = MagicMock(spec=Output)
        _format_task_result(result, output)

        output.field.assert_any_call("Task ID", "task-123", dim_value=True)
        output.state.assert_called_with("State", "completed")
        output.markdown.assert_called_with("Output text here")

    def test_format_task_result_no_text(self):
        """Test formatting a task result without text."""
        from a2a_handler.cli.task import _format_task_result
        from a2a_handler.common import Output
        from unittest.mock import MagicMock

        mock_task = _make_task(TaskState.working)
        result = TaskResult(task=mock_task, text="")

        output = MagicMock(spec=Output)
        _format_task_result(result, output)

        output.markdown.assert_not_called()
