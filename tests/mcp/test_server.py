"""Tests for MCP server tool registration and validation guards."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from a2a.types import (
    AgentCard,
    AgentSkill,
    Task,
    TaskState,
    TaskStatus,
)

from a2a_handler.mcp.server import create_mcp_server
from a2a_handler.session import AgentSession
from a2a_handler.validation import ValidationResult, ValidationSource
from tests.factories import make_agent_card, make_push_config


def _tool_fn(server, name: str):
    tool = server._tool_manager.get_tool(name)  # pyright: ignore[reportPrivateUsage]
    assert tool is not None
    return tool.fn


def _mock_http():
    mock = AsyncMock()
    mock.__aenter__.return_value = mock
    mock.__aexit__.return_value = None
    return mock


def _make_agent_card(name: str = "TestAgent") -> AgentCard:
    return make_agent_card(
        name=name,
        description="A test agent",
        version="1.0",
        url="http://localhost:8000",
        streaming=True,
        push_notifications=False,
        skills=[
            AgentSkill(id="s1", name="skill1", description="A skill", tags=["test"])
        ],
    )


def _make_task(
    task_id: str = "task-1",
    context_id: str = "ctx-1",
    state: TaskState = TaskState.TASK_STATE_COMPLETED,
) -> Task:
    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=state),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_mcp_server_registers_core_tools() -> None:
    server = create_mcp_server()
    names = {tool.name for tool in server._tool_manager.list_tools()}  # pyright: ignore[reportPrivateUsage]

    assert "send_message" in names
    assert "get_task" in names
    assert "set_task_notification" in names
    assert "list_sessions" in names


# ---------------------------------------------------------------------------
# validate_agent_card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_agent_card_from_file_success() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "validate_agent_card")

    result = ValidationResult(
        valid=True,
        source="/tmp/card.json",
        source_type=ValidationSource.FILE,
        agent_card=_make_agent_card(),
    )

    with patch(
        "a2a_handler.mcp.server.validate_agent_card_from_file", return_value=result
    ):
        resp = await fn(source="/tmp/card.json", from_file=True)

    assert resp["valid"] is True
    assert resp["source_type"] == "file"
    assert resp["agent_name"] == "TestAgent"
    assert resp["capabilities"]["streaming"] is True
    assert resp["skills"] == [{"id": "s1", "name": "skill1"}]


@pytest.mark.asyncio
async def test_validate_agent_card_from_url_success() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "validate_agent_card")

    result = ValidationResult(
        valid=True,
        source="http://localhost:8000",
        source_type=ValidationSource.URL,
        agent_card=_make_agent_card(),
    )

    with patch(
        "a2a_handler.mcp.server.validate_agent_card_from_url",
        new_callable=AsyncMock,
        return_value=result,
    ):
        resp = await fn(source="http://localhost:8000", from_file=False)

    assert resp["valid"] is True
    assert resp["source_type"] == "url"


@pytest.mark.asyncio
async def test_validate_agent_card_rejects_invalid_url() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "validate_agent_card")

    with pytest.raises(ValueError, match="invalid_agent_url"):
        await fn(source="not-a-url", from_file=False)


# ---------------------------------------------------------------------------
# get_agent_card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_agent_card_success() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "get_agent_card")

    card = _make_agent_card()
    mock_service = AsyncMock()
    mock_service.get_card.return_value = card

    with (
        patch("a2a_handler.mcp.server._build_http_client", return_value=_mock_http()),
        patch("a2a_handler.mcp.server.A2AService", return_value=mock_service),
    ):
        resp = await fn(agent_url="http://localhost:8000")

    assert resp["name"] == "TestAgent"
    assert resp["supportedInterfaces"][0]["url"] == "http://localhost:8000"


@pytest.mark.asyncio
async def test_get_agent_card_rejects_invalid_url() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "get_agent_card")

    with pytest.raises(ValueError, match="invalid_agent_url"):
        await fn(agent_url="bad-url")


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_rejects_invalid_agent_url() -> None:
    server = create_mcp_server()
    send_message = _tool_fn(server, "send_message")

    with pytest.raises(ValueError, match="invalid_agent_url"):
        await send_message(agent_url="not-a-url", message="hello")


@pytest.mark.asyncio
async def test_send_message_success() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "send_message")

    task = _make_task()

    mock_service = AsyncMock()
    mock_service.send.return_value = task

    with (
        patch("a2a_handler.mcp.server._build_http_client", return_value=_mock_http()),
        patch("a2a_handler.mcp.server.A2AService", return_value=mock_service),
        patch("a2a_handler.mcp.server.update_session") as mock_update,
    ):
        resp = await fn(agent_url="http://localhost:8000", message="hi")

    assert resp["id"] == "task-1"
    assert resp["contextId"] == "ctx-1"
    assert resp["status"]["state"] == "TASK_STATE_COMPLETED"
    mock_update.assert_called_once_with("http://localhost:8000", "ctx-1", "task-1")


@pytest.mark.asyncio
async def test_send_message_with_use_session() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "send_message")

    task = _make_task()

    mock_service = AsyncMock()
    mock_service.send.return_value = task

    session = AgentSession(
        agent_url="http://localhost:8000",
        context_id="saved-ctx",
        task_id="saved-task",
    )

    with (
        patch("a2a_handler.mcp.server._build_http_client", return_value=_mock_http()),
        patch("a2a_handler.mcp.server.A2AService", return_value=mock_service),
        patch("a2a_handler.mcp.server.update_session"),
        patch("a2a_handler.mcp.server.get_session", return_value=session),
    ):
        resp = await fn(
            agent_url="http://localhost:8000", message="hi", use_session=True
        )

    mock_service.send.assert_called_once_with("hi", "saved-ctx", "saved-task")
    assert resp["id"] == "task-1"
    assert resp["contextId"] == "ctx-1"


@pytest.mark.asyncio
async def test_send_message_with_bearer_token() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "send_message")

    task = _make_task()

    mock_service = AsyncMock()
    mock_service.send.return_value = task

    with (
        patch("a2a_handler.mcp.server._build_http_client", return_value=_mock_http()),
        patch(
            "a2a_handler.mcp.server.A2AService", return_value=mock_service
        ) as mock_cls,
        patch("a2a_handler.mcp.server.update_session"),
    ):
        resp = await fn(
            agent_url="http://localhost:8000",
            message="hi",
            bearer_token="tok-123",
        )

    assert resp["id"] == "task-1"
    assert resp["status"]["state"] == "TASK_STATE_COMPLETED"
    _, kwargs = mock_cls.call_args
    assert kwargs["credentials"] is not None


@pytest.mark.asyncio
async def test_send_message_rejects_reserved_custom_header() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "send_message")

    with pytest.raises(ValueError, match="reserved_header"):
        await fn(
            agent_url="http://localhost:8000",
            message="hi",
            custom_headers={"Authorization": "Bearer shadow"},
        )


# ---------------------------------------------------------------------------
# get_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_success() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "get_task")

    task = _make_task(state=TaskState.TASK_STATE_WORKING)

    mock_service = AsyncMock()
    mock_service.get_task.return_value = task

    with (
        patch("a2a_handler.mcp.server._build_http_client", return_value=_mock_http()),
        patch("a2a_handler.mcp.server.A2AService", return_value=mock_service),
    ):
        resp = await fn(agent_url="http://localhost:8000", task_id="task-1")

    assert resp["id"] == "task-1"
    assert resp["contextId"] == "ctx-1"
    assert resp["status"]["state"] == "TASK_STATE_WORKING"


@pytest.mark.asyncio
async def test_get_task_rejects_invalid_url() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "get_task")

    with pytest.raises(ValueError, match="invalid_agent_url"):
        await fn(agent_url="nope", task_id="task-1")


@pytest.mark.asyncio
async def test_get_task_rejects_invalid_task_id() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "get_task")

    with pytest.raises(ValueError, match="invalid_control_chars"):
        await fn(agent_url="http://localhost:8000", task_id="bad\x00id")


# ---------------------------------------------------------------------------
# cancel_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_task_success() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "cancel_task")

    task = _make_task(state=TaskState.TASK_STATE_CANCELED)

    mock_service = AsyncMock()
    mock_service.cancel_task.return_value = task

    with (
        patch("a2a_handler.mcp.server._build_http_client", return_value=_mock_http()),
        patch("a2a_handler.mcp.server.A2AService", return_value=mock_service),
    ):
        resp = await fn(agent_url="http://localhost:8000", task_id="task-1")

    assert resp["id"] == "task-1"
    assert resp["contextId"] == "ctx-1"
    assert resp["status"]["state"] == "TASK_STATE_CANCELED"


# ---------------------------------------------------------------------------
# set_task_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_task_notification_rejects_invalid_webhook() -> None:
    server = create_mcp_server()
    set_task_notification = _tool_fn(server, "set_task_notification")

    with pytest.raises(ValueError, match="invalid_webhook_url"):
        await set_task_notification(
            agent_url="http://localhost:8000",
            task_id="task-123",
            webhook_url="not-a-url",
        )


@pytest.mark.asyncio
async def test_set_task_notification_success() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "set_task_notification")

    config = make_push_config(
        task_id="task-1",
        url="https://hooks.example.com/notify",
        token="secret-token-value-here-long",
        config_id="cfg-1",
    )

    mock_service = AsyncMock()
    mock_service.set_push_config.return_value = config

    with (
        patch("a2a_handler.mcp.server._build_http_client", return_value=_mock_http()),
        patch("a2a_handler.mcp.server.A2AService", return_value=mock_service),
    ):
        resp = await fn(
            agent_url="http://localhost:8000",
            task_id="task-1",
            webhook_url="https://hooks.example.com/notify",
        )

    assert resp["taskId"] == "task-1"
    assert resp["url"] == "https://hooks.example.com/notify"
    assert resp["token"] == "secr...long"
    assert resp["id"] == "cfg-1"


# ---------------------------------------------------------------------------
# get_task_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_notification_success() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "get_task_notification")

    config = make_push_config(
        task_id="task-1",
        url="https://hooks.example.com/notify",
        token="abcdefghij1234567890xyz",
        config_id="cfg-2",
    )

    mock_service = AsyncMock()
    mock_service.get_push_config.return_value = config

    with (
        patch("a2a_handler.mcp.server._build_http_client", return_value=_mock_http()),
        patch("a2a_handler.mcp.server.A2AService", return_value=mock_service),
    ):
        resp = await fn(agent_url="http://localhost:8000", task_id="task-1")

    assert resp["taskId"] == "task-1"
    assert resp["url"] == "https://hooks.example.com/notify"
    assert resp["token"] == "abcd...0xyz"
    assert resp["id"] == "cfg-2"


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sessions_success() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "list_sessions")

    sessions = [
        AgentSession(agent_url="http://a:8000", context_id="c1", task_id="t1"),
        AgentSession(agent_url="http://b:8000", context_id="c2", task_id=None),
    ]

    mock_store = MagicMock()
    mock_store.list_all.return_value = sessions

    with patch("a2a_handler.mcp.server.get_session_store", return_value=mock_store):
        resp = await fn()

    assert resp["count"] == 2
    assert resp["sessions"][0]["agent_url"] == "http://a:8000"
    assert resp["sessions"][0]["context_id"] == "c1"
    assert resp["sessions"][1]["task_id"] is None


# ---------------------------------------------------------------------------
# get_session_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_info_success() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "get_session_info")

    session = AgentSession(
        agent_url="http://localhost:8000", context_id="c1", task_id="t1"
    )

    with patch("a2a_handler.mcp.server.get_session", return_value=session):
        resp = await fn(agent_url="http://localhost:8000")

    assert resp["agent_url"] == "http://localhost:8000"
    assert resp["context_id"] == "c1"
    assert resp["task_id"] == "t1"


@pytest.mark.asyncio
async def test_get_session_info_rejects_invalid_url() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "get_session_info")

    with pytest.raises(ValueError, match="invalid_agent_url"):
        await fn(agent_url="nope")


# ---------------------------------------------------------------------------
# clear_session_data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_session_data_specific_agent() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "clear_session_data")

    with patch("a2a_handler.mcp.server.clear_session") as mock_clear:
        resp = await fn(agent_url="http://localhost:8000")

    mock_clear.assert_called_once_with("http://localhost:8000")
    assert resp["cleared"] == "Session for http://localhost:8000"


@pytest.mark.asyncio
async def test_clear_session_data_all() -> None:
    server = create_mcp_server()
    fn = _tool_fn(server, "clear_session_data")

    with patch("a2a_handler.mcp.server.clear_session") as mock_clear:
        resp = await fn(agent_url=None)

    mock_clear.assert_called_once_with()
    assert resp["cleared"] == "All sessions"
