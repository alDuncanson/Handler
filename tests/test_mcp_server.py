"""Tests for MCP server tool registration and validation guards."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import a2a_handler.session as session_module
from a2a_handler.mcp.server import create_mcp_server
from a2a_handler.session import SessionStore


def _tool_fn(server, name: str):
    tool = server._tool_manager.get_tool(name)  # pyright: ignore[reportPrivateUsage]
    assert tool is not None
    return tool.fn


def test_mcp_server_registers_core_tools() -> None:
    server = create_mcp_server()
    names = {tool.name for tool in server._tool_manager.list_tools()}  # pyright: ignore[reportPrivateUsage]

    assert "send_message" in names
    assert "get_task" in names
    assert "set_task_notification" in names
    assert "list_sessions" in names


@pytest.mark.asyncio
async def test_send_message_rejects_invalid_agent_url() -> None:
    server = create_mcp_server()
    send_message = _tool_fn(server, "send_message")

    with pytest.raises(ValueError, match="invalid_agent_url"):
        await send_message(agent_url="not-a-url", message="hello")


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
async def test_set_agent_credentials_accepts_valid_input() -> None:
    server = create_mcp_server()
    set_agent_credentials = _tool_fn(server, "set_agent_credentials")

    with patch("a2a_handler.mcp.server.set_credentials") as mock_set:
        result = await set_agent_credentials(
            agent_url="http://localhost:8000",
            api_key="secret-key",
        )

    assert result == {"agent_url": "http://localhost:8000", "auth_type": "api_key"}
    mock_set.assert_called_once()


@pytest.mark.asyncio
async def test_set_agent_credentials_rejects_missing_auth_values() -> None:
    server = create_mcp_server()
    set_agent_credentials = _tool_fn(server, "set_agent_credentials")

    with pytest.raises(ValueError, match="missing_auth_arguments"):
        await set_agent_credentials(agent_url="http://localhost:8000")


@pytest.mark.asyncio
async def test_set_agent_credentials_rejects_multiple_auth_values() -> None:
    server = create_mcp_server()
    set_agent_credentials = _tool_fn(server, "set_agent_credentials")

    with patch("a2a_handler.mcp.server.set_credentials") as mock_set:
        with pytest.raises(ValueError, match="invalid_auth_arguments"):
            await set_agent_credentials(
                agent_url="http://localhost:8000",
                bearer_token="token",
                api_key="secret-key",
            )

    mock_set.assert_not_called()


@pytest.mark.asyncio
async def test_set_agent_credentials_serializes_with_keyring_metadata() -> None:
    server = create_mcp_server()
    set_agent_credentials = _tool_fn(server, "set_agent_credentials")
    agent_url = "http://localhost:8000"

    with tempfile.TemporaryDirectory() as temp_directory:
        store = SessionStore(session_directory=Path(temp_directory))

        with (
            patch.object(session_module, "_global_session_store", store),
            patch.object(
                SessionStore,
                "_store_credential_in_keyring",
                return_value=True,
            ),
        ):
            result = await set_agent_credentials(
                agent_url=agent_url,
                bearer_token="secret-token",
            )

        assert result == {"agent_url": agent_url, "auth_type": "bearer"}

        serialized = json.loads(store.session_file_path.read_text())
        credentials_data = serialized[agent_url]["credentials"]
        assert credentials_data["storage"] == "keyring"
        assert "value" not in credentials_data
