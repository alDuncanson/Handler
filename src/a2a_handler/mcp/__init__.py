"""MCP server exposing Handler's A2A capabilities as MCP tools and resources."""

from a2a_handler.mcp.server import create_mcp_server, run_mcp_server

__all__ = ["create_mcp_server", "run_mcp_server"]
