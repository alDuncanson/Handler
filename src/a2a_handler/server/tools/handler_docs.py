"""Hosted Handler documentation toolset for the embedded Handler agent."""

from __future__ import annotations

import os

from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StreamableHTTPConnectionParams,
)

from a2a_handler.common import get_logger
from a2a_handler.common.dotenv import load_runtime_dotenv

logger = get_logger(__name__)

DEFAULT_HANDLER_DOCS_MCP_URL = "https://handler.alduncanson.com/mcp"


def create_handler_docs_toolset(mcp_url: str | None = None) -> McpToolset:
    """Create the MCP toolset that lets the agent consult Handler docs.

    Args:
        mcp_url: Optional MCP endpoint override. If not provided, uses the
            HANDLER_DOCS_MCP_URL environment variable or the hosted docs MCP.

    Returns:
        A configured ADK MCP toolset for Handler documentation tools.
    """
    load_runtime_dotenv()

    effective_mcp_url = (
        mcp_url or os.getenv("HANDLER_DOCS_MCP_URL") or DEFAULT_HANDLER_DOCS_MCP_URL
    )
    logger.info("Enabling Handler docs MCP toolset at %s", effective_mcp_url)

    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=effective_mcp_url,
            timeout=10.0,
            sse_read_timeout=300.0,
        ),
        tool_name_prefix="handler_docs",
    )
