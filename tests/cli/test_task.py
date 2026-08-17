"""Tests for task CLI commands."""

import os

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from unittest.mock import patch as mock_patch

from click.testing import CliRunner
from a2a.types import (
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)

from a2a_handler.cli.task import task
from a2a_handler.service import StreamEvent
from tests.factories import make_push_config


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


def _make_task(
    state: TaskState = TaskState.TASK_STATE_COMPLETED,
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
        mock_task = Task(
            id="task-123",
            context_id="ctx-123",
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
            history=[
                Message(
                    message_id="msg-1",
                    role=Role.ROLE_AGENT,
                    parts=[Part(text="Task output text")],
                    context_id="ctx-123",
                )
            ],
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
            mock_service.get_task.return_value = mock_task
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
        mock_task = _make_task(TaskState.TASK_STATE_COMPLETED)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = mock_task
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
        mock_task = _make_task(TaskState.TASK_STATE_COMPLETED)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = mock_task
            mock_service_cls.return_value = mock_service

            with mock_patch.dict(os.environ, {"TEST_BEARER": "my-token"}):
                result = runner.invoke(
                    task,
                    [
                        "get",
                        "--url",
                        "http://localhost:8000",
                        "--task",
                        "task-123",
                        "--bearer-env",
                        "TEST_BEARER",
                    ],
                )

            assert result.exit_code == 0
            # Verify the service was created with credentials
            call_kwargs = mock_service_cls.call_args.kwargs
            assert call_kwargs["credentials"] is not None

    def test_task_get_with_api_key_auth(self, runner):
        """Test task get with API key override."""
        mock_task = _make_task(TaskState.TASK_STATE_COMPLETED)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = mock_task
            mock_service_cls.return_value = mock_service

            with mock_patch.dict(os.environ, {"TEST_API_KEY": "my-key"}):
                result = runner.invoke(
                    task,
                    [
                        "get",
                        "--url",
                        "http://localhost:8000",
                        "--task",
                        "task-123",
                        "--api-key-env",
                        "TEST_API_KEY",
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
        mock_task = _make_task(TaskState.TASK_STATE_COMPLETED)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = mock_task
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


class TestTaskIdArgument:
    """Tests for supplying a task ID positionally instead of with --task."""

    @pytest.mark.parametrize(
        "command,extra",
        [
            ("get", []),
            ("cancel", []),
            (
                "notification",
                ["--webhook-url", "http://webhook.example.com"],
            ),
        ],
    )
    def test_task_id_accepted_positionally(self, runner, command, extra):
        """Every task command takes the ID positionally as well as via --task."""
        argv = (
            ["notification", "set", "task-123"]
            if command == "notification"
            else [command, "task-123"]
        )
        argv += ["--url", "http://localhost:8000", *extra]

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = _make_task()
            mock_service.cancel_task.return_value = _make_task(
                state=TaskState.TASK_STATE_CANCELED
            )
            mock_service.set_push_config.return_value = make_push_config()
            mock_service_cls.return_value = mock_service

            result = runner.invoke(task, argv)

        assert result.exit_code == 0, result.output

    def test_positional_and_option_agree(self, runner):
        """Passing the same ID both ways is accepted rather than rejected."""
        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = _make_task()
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "get",
                    "task-123",
                    "--task",
                    "task-123",
                    "--url",
                    "http://localhost:8000",
                ],
            )

        assert result.exit_code == 0, result.output

    def test_conflicting_task_ids_rejected(self, runner):
        """Two different IDs is ambiguous and must not silently pick one."""
        result = runner.invoke(
            task,
            [
                "get",
                "task-abc",
                "--task",
                "task-xyz",
                "--url",
                "http://localhost:8000",
            ],
        )

        assert result.exit_code != 0
        assert "Conflicting task IDs" in result.output

    def test_missing_task_id_reports_both_forms(self, runner):
        """Omitting the ID entirely explains both ways to supply it."""
        result = runner.invoke(task, ["get", "--url", "http://localhost:8000"])

        assert result.exit_code != 0
        assert "Missing task ID" in result.output
        assert "--task" in result.output

    def test_task_id_from_json_params_alone(self, runner):
        """--params may carry task_id without the flag or positional argument."""
        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_task.return_value = _make_task()
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "get",
                    "--url",
                    "http://localhost:8000",
                    "--params",
                    '{"task_id": "task-123"}',
                ],
            )

        assert result.exit_code == 0, result.output
        mock_service.get_task.assert_awaited_once_with("task-123", None)


class TestTaskCancel:
    """Tests for task cancel command."""

    def test_task_cancel_success(self, runner):
        """Test successful task cancel command."""
        mock_task = _make_task(TaskState.TASK_STATE_CANCELED)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.cancel_task.return_value = mock_task
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
            assert '"TASK_STATE_CANCELED"' in result.output

    def test_task_cancel_with_bearer(self, runner):
        """Test task cancel with bearer token."""
        mock_task = _make_task(TaskState.TASK_STATE_CANCELED)

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.cancel_task.return_value = mock_task
            mock_service_cls.return_value = mock_service

            with mock_patch.dict(os.environ, {"TEST_BEARER": "token"}):
                result = runner.invoke(
                    task,
                    [
                        "cancel",
                        "--url",
                        "http://localhost:8000",
                        "--task",
                        "task-123",
                        "--bearer-env",
                        "TEST_BEARER",
                    ],
                )

            assert result.exit_code == 0


class TestTaskResubscribe:
    """Tests for task resubscribe command."""

    def test_task_resubscribe_streams_events(self, runner):
        """Test task resubscribe yields stream events."""
        mock_task = _make_task(TaskState.TASK_STATE_WORKING)

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
            patch("a2a_handler.cli.task.build_streaming_http_client") as mock_client,
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
        mock_task = _make_task(TaskState.TASK_STATE_COMPLETED)

        async def mock_resubscribe(*args, **kwargs):
            yield StreamEvent(event_type="status", task=mock_task)

        with (
            patch("a2a_handler.cli.task.build_streaming_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = MagicMock()
            mock_service.resubscribe = mock_resubscribe
            mock_service_cls.return_value = mock_service

            with mock_patch.dict(os.environ, {"TEST_API_KEY": "my-key"}):
                result = runner.invoke(
                    task,
                    [
                        "resubscribe",
                        "--url",
                        "http://localhost:8000",
                        "--task",
                        "task-123",
                        "--api-key-env",
                        "TEST_API_KEY",
                    ],
                )

            assert result.exit_code == 0


class TestTaskNotificationSet:
    """Tests for task notification set command."""

    def test_notification_set_success(self, runner):
        """Test successful notification set command."""
        mock_config = make_push_config(
            task_id="task-123",
            url="http://webhook.example.com",
            token="secret-token",
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
            assert '"taskId"' in result.output
            assert "secret-token" not in result.output
            assert "secr...oken" in result.output

    def test_notification_set_with_token(self, runner):
        """Test notification set with authentication token."""
        mock_config = make_push_config(
            task_id="task-123",
            url="http://webhook.example.com",
            token="webhook-token",
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
            assert "webhook-token" not in result.output
            assert "webh...oken" in result.output

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


class TestTaskNotificationList:
    """Tests for task notification list command."""

    def test_notification_list_success(self, runner):
        """Listing shows every config with tokens redacted."""
        configs = [
            make_push_config(
                task_id="task-123",
                url="http://webhook.example.com/a",
                token="secret-token",
                config_id="cfg-1",
            ),
            make_push_config(
                task_id="task-123",
                url="http://webhook.example.com/b",
                config_id="cfg-2",
            ),
        ]

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.list_all_push_configs.return_value = configs
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "notification",
                    "list",
                    "task-123",
                    "--url",
                    "http://localhost:8000",
                ],
            )

            assert result.exit_code == 0
            assert "cfg-1" in result.output
            assert "cfg-2" in result.output
            assert "secret-token" not in result.output
            mock_service.list_all_push_configs.assert_called_once_with(
                "task-123", page_size=None
            )

    def test_notification_list_requires_task_id(self, runner):
        """Listing without a task ID fails before any network call."""
        result = runner.invoke(
            task,
            ["notification", "list", "--url", "http://localhost:8000"],
        )
        assert result.exit_code != 0


class TestTaskNotificationRemove:
    """Tests for task notification remove command."""

    def test_notification_remove_success(self, runner):
        """Removing reports what was deleted."""
        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.delete_push_config.return_value = None
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "notification",
                    "remove",
                    "task-123",
                    "--url",
                    "http://localhost:8000",
                    "--config-id",
                    "cfg-1",
                ],
            )

            assert result.exit_code == 0
            assert "cfg-1" in result.output
            mock_service.delete_push_config.assert_called_once_with("task-123", "cfg-1")

    def test_notification_remove_requires_config_id(self, runner):
        """Removing without a config ID fails before any network call."""
        result = runner.invoke(
            task,
            [
                "notification",
                "remove",
                "task-123",
                "--url",
                "http://localhost:8000",
            ],
        )
        assert result.exit_code != 0
        assert "config-id" in result.output.lower()

    def test_notification_remove_surfaces_server_error(self, runner):
        """A missing config fails loudly with the server's message."""
        from a2a.client.errors import A2AClientError

        with (
            patch("a2a_handler.cli.task.build_http_client") as mock_client,
            patch("a2a_handler.cli.task.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.delete_push_config.side_effect = A2AClientError(
                "config not found"
            )
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                task,
                [
                    "notification",
                    "remove",
                    "task-123",
                    "--url",
                    "http://localhost:8000",
                    "--config-id",
                    "cfg-missing",
                ],
            )

            assert result.exit_code != 0
            assert "config not found" in result.output


class TestTaskNotificationGet:
    """Tests for task notification get command."""

    def test_notification_get_success(self, runner):
        """Test successful notification get command."""
        mock_config = make_push_config(
            task_id="task-123",
            url="http://webhook.example.com",
            token="secret-token",
            config_id="config-id-123",
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
            assert "secret-token" not in result.output
            assert "secr...oken" in result.output

    def test_notification_get_with_config_id(self, runner):
        """Test notification get with specific config ID."""
        mock_config = make_push_config(
            task_id="task-123",
            url="http://webhook.example.com",
            config_id="specific-config-id",
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


class TestFormatTask:
    """Tests for _format_task helper."""

    def test_format_task_completed(self):
        """Test formatting a completed task emits JSON."""
        from a2a_handler.cli.task import _format_task
        from a2a_handler.common import Output
        from unittest.mock import MagicMock

        mock_task = Task(
            id="task-123",
            context_id="ctx-abc",
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
            history=[
                Message(
                    message_id="msg-1",
                    role=Role.ROLE_AGENT,
                    parts=[Part(text="Output text here")],
                    context_id="ctx-abc",
                )
            ],
        )

        output = MagicMock(spec=Output)
        _format_task(mock_task, output)

        output.json.assert_called_once()
        call_data = output.json.call_args[0][0]
        assert call_data["id"] == "task-123"
        assert call_data["status"]["state"] == "TASK_STATE_COMPLETED"

    def test_format_task_no_text(self):
        """Test formatting a task without text emits JSON."""
        from a2a_handler.cli.task import _format_task
        from a2a_handler.common import Output
        from unittest.mock import MagicMock

        mock_task = _make_task(TaskState.TASK_STATE_WORKING)

        output = MagicMock(spec=Output)
        _format_task(mock_task, output)

        output.json.assert_called_once()
