"""LLM agent creation and configuration."""

import os

from google.adk.agents.llm_agent import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StreamableHTTPConnectionParams,
)

from a2a_handler.common import get_logger
from a2a_handler.common.dotenv import load_runtime_dotenv

logger = get_logger(__name__)

DEFAULT_OLLAMA_API_BASE = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma4:e2b"
DEFAULT_HANDLER_DOCS_MCP_URL = "https://handler.alduncanson.com/mcp"


def _handler_docs_mcp_enabled() -> bool:
    """Return whether the hosted Handler docs MCP toolset should be enabled."""
    enabled = os.getenv("HANDLER_DOCS_MCP_ENABLED")
    if enabled is None:
        return True
    return enabled.strip().lower() not in {"0", "false", "no", "off"}


def create_language_model(model: str | None = None) -> LiteLlm:
    """Create an Ollama language model via LiteLLM.

    Args:
        model: Model identifier. If None, uses OLLAMA_MODEL env var or default.

    Returns:
        LiteLlm instance configured for Ollama
    """
    load_runtime_dotenv()

    effective_model = model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    ollama_api_base = os.getenv("OLLAMA_API_BASE", DEFAULT_OLLAMA_API_BASE)
    logger.info(
        "Creating agent with Ollama model: %s at %s",
        effective_model,
        ollama_api_base,
    )

    return LiteLlm(
        model=f"ollama_chat/{effective_model}",
        api_base=ollama_api_base,
        reasoning_effort="none",
    )


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
        mcp_url
        or os.getenv("HANDLER_DOCS_MCP_URL")
        or DEFAULT_HANDLER_DOCS_MCP_URL
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


def create_llm_agent(model: str | None = None) -> Agent:
    """Create and configure the A2A agent using Ollama via LiteLLM.

    Args:
        model: Ollama model identifier (e.g., 'gemma4:e2b')

    Returns:
        Configured ADK Agent instance
    """
    language_model = create_language_model(model)

    instruction = """You are Handler's Agent, the built-in assistant for the Handler application.

Handler is an A2A protocol client published on PyPI as `a2a-handler`. It provides tools for developers to communicate with, test, and debug A2A-compatible agents.

You have access to Handler's hosted documentation through an MCP server. Use the documentation tools when answering Handler-specific questions about commands, configuration, workflows, authentication, MCP, local servers, or troubleshooting. Prefer current documentation over memory, and cite the relevant page or command when helpful.

Handler's architecture consists of:
1. **TUI** - An interactive terminal interface (Textual-based) for managing agent connections, sending messages, and viewing streaming responses
2. **CLI** - A rich-click powered command-line interface for scripting and automation
3. **A2AService** - A unified service layer wrapping the a2a-sdk for protocol operations
4. **Server Agent** - A local A2A-compatible agent (you!) for testing, built with Google ADK
5. **MCP Server** - A bridge that exposes Handler's A2A operations as agent-friendly tools

Handler supports streaming responses, push notifications, session persistence, and both JSON and formatted text output.

When users want to operate on another A2A agent, explain the Handler CLI/TUI/MCP path and provide concrete commands such as `handler card get`, `handler message send`, `handler task get`, or `handler mcp` where appropriate.

Be conversational, helpful, concise, and practical."""

    tools = []
    if _handler_docs_mcp_enabled():
        tools.append(create_handler_docs_toolset())
    else:
        logger.info("Handler docs MCP toolset disabled by HANDLER_DOCS_MCP_ENABLED")

    agent = Agent(
        name="Handler",
        model=language_model,
        description=(
            "Handler's built-in assistant for A2A development, Handler usage, "
            "and documentation-backed support"
        ),
        instruction=instruction,
        tools=tools,
    )

    logger.info("Agent created successfully: %s", agent.name)
    return agent
