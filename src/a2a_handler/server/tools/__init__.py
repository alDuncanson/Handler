"""Tool factories and implementations for Handler's embedded agent."""

from .a2a_docs import (
    DEFAULT_A2A_LLMS_FULL_URL,
    DEFAULT_A2A_LLMS_URL,
    create_a2a_docs_tools,
    fetch_a2a_protocol_docs,
    search_a2a_protocol_docs,
)
from .handler_docs import DEFAULT_HANDLER_DOCS_MCP_URL, create_handler_docs_toolset
from .source import create_handler_source_tools, search_handler_source

__all__ = [
    "DEFAULT_A2A_LLMS_FULL_URL",
    "DEFAULT_A2A_LLMS_URL",
    "DEFAULT_HANDLER_DOCS_MCP_URL",
    "create_a2a_docs_tools",
    "create_handler_docs_toolset",
    "create_handler_source_tools",
    "fetch_a2a_protocol_docs",
    "search_a2a_protocol_docs",
    "search_handler_source",
]
