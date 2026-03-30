"""Tests for MCP server tool registration and validation guards."""

import pytest

from a2a_handler.mcp.server import create_mcp_server


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



