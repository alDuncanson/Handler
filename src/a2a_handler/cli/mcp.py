"""MCP server CLI command."""

from typing import Literal

import rich_click as click

from a2a_handler.common import get_logger

log = get_logger(__name__)

TransportType = Literal["stdio", "sse", "streamable-http"]


@click.command()
@click.option(
    "--transport",
    "-t",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    default="stdio",
    help="Transport protocol to use",
    show_default=True,
)
def mcp(transport: TransportType) -> None:
    """Run a local MCP server exposing A2A capabilities.

    This starts an MCP (Model Context Protocol) server that exposes Handler's
    A2A functionality as MCP tools and resources. You can connect to this
    server from any MCP-compatible client (like Claude Desktop, Cursor, etc.).

    The server provides tools for:

    \b
    Card Tools:
    - validate_agent_card: Validate an agent card from URL or file
    - get_agent_card: Retrieve an agent's full card details

    \b
    Message Tools:
    - send_message: Send messages to agents with session/auth support

    \b
    Task Tools:
    - get_task: Get task status and details
    - cancel_task: Cancel a running task
    - set_task_notification: Configure push notification webhooks
    - get_task_notification: Get push notification config

    \b
    Session Tools:
    - list_sessions: List all saved sessions
    - get_session_info: Get session for a specific agent
    - clear_session_data: Clear saved session state

    \b
    Auth Tools:
    - set_agent_credentials: Save bearer token or API key
    - clear_agent_credentials: Remove saved credentials

    Example configuration for Claude Desktop (claude_desktop_config.json):

        {
          "mcpServers": {
            "handler": {
              "command": "handler",
              "args": ["mcp"]
            }
          }
        }
    """
    from a2a_handler.mcp import run_mcp_server

    log.info("Starting MCP server with %s transport", transport)
    run_mcp_server(transport=transport)
