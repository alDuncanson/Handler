"""LLM agent creation and configuration."""

import os
import re
import urllib.request
from functools import lru_cache

from google.adk.agents.llm_agent import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool
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
DEFAULT_A2A_LLMS_URL = "https://a2a-protocol.org/llms.txt"
DEFAULT_A2A_LLMS_FULL_URL = "https://a2a-protocol.org/llms-full.txt"
A2A_DOCS_FETCH_TIMEOUT_SECONDS = 10
A2A_DOCS_MAX_FETCH_CHARS = 20_000
A2A_DOCS_MAX_SEARCH_CHARS = 12_000


def _handler_docs_mcp_enabled() -> bool:
    """Return whether the hosted Handler docs MCP toolset should be enabled."""
    enabled = os.getenv("HANDLER_DOCS_MCP_ENABLED")
    if enabled is None:
        return True
    return enabled.strip().lower() not in {"0", "false", "no", "off"}


def _a2a_docs_tools_enabled() -> bool:
    """Return whether the A2A protocol documentation tools should be enabled."""
    enabled = os.getenv("A2A_DOCS_TOOLS_ENABLED")
    if enabled is None:
        return True
    return enabled.strip().lower() not in {"0", "false", "no", "off"}


def _a2a_docs_url(source: str) -> str:
    """Return the configured URL for the requested A2A docs source."""
    normalized = source.strip().lower()
    if normalized in {"full", "llms-full", "llms-full.txt"}:
        return os.getenv("A2A_LLMS_FULL_URL", DEFAULT_A2A_LLMS_FULL_URL)
    return os.getenv("A2A_LLMS_URL", DEFAULT_A2A_LLMS_URL)


@lru_cache(maxsize=4)
def _fetch_a2a_docs_text(source: str) -> str:
    """Fetch and cache A2A protocol docs from the public llms text endpoints."""
    url = _a2a_docs_url(source)
    request = urllib.request.Request(url, headers={"User-Agent": "a2a-handler/agent"})
    with urllib.request.urlopen(
        request,
        timeout=A2A_DOCS_FETCH_TIMEOUT_SECONDS,
    ) as response:
        return response.read().decode("utf-8", errors="replace")


def _bounded_text(text: str, max_chars: int) -> str:
    """Return text truncated to a safe size for an LLM tool response."""
    safe_max_chars = max(1_000, min(max_chars, A2A_DOCS_MAX_FETCH_CHARS))
    if len(text) <= safe_max_chars:
        return text
    return (
        text[:safe_max_chars]
        + "\n\n[truncated] Use search_a2a_protocol_docs for targeted excerpts."
    )


def fetch_a2a_protocol_docs(source: str = "summary", max_chars: int = 12_000) -> str:
    """Fetch A2A protocol documentation text.

    Args:
        source: Use "summary" for llms.txt or "full" for llms-full.txt.
        max_chars: Maximum characters to return. Large responses are truncated.

    Returns:
        A bounded documentation excerpt from the official A2A protocol site.
    """
    try:
        return _bounded_text(_fetch_a2a_docs_text(source), max_chars)
    except Exception as error:
        return f"Failed to fetch A2A protocol docs: {error}"


def _line_score(line: str, terms: list[str]) -> int:
    """Score a line by query term frequency."""
    lowered = line.lower()
    return sum(lowered.count(term) for term in terms)


def search_a2a_protocol_docs(query: str, max_results: int = 5) -> str:
    """Search official A2A protocol documentation excerpts.

    Args:
        query: Plain-text search terms, such as "tasks vs messages".
        max_results: Maximum matching excerpts to return.

    Returns:
        Ranked, rg-style excerpts from the A2A llms-full.txt documentation.
    """
    terms = [term.lower() for term in re.findall(r"\w+", query) if len(term) > 1]
    if not terms:
        return (
            "Provide one or more search terms, for example: tasks messages artifacts."
        )

    try:
        text = _fetch_a2a_docs_text("full")
        source = _a2a_docs_url("full")
    except Exception:
        try:
            text = _fetch_a2a_docs_text("summary")
            source = _a2a_docs_url("summary")
        except Exception as error:
            return f"Failed to search A2A protocol docs: {error}"

    lines = text.splitlines()
    scored_lines = [
        (score, index)
        for index, line in enumerate(lines)
        if (score := _line_score(line, terms)) > 0
    ]
    if not scored_lines:
        return f"No A2A protocol docs matches for: {query}"

    max_results = max(1, min(max_results, 10))
    excerpts: list[str] = [f"Source: {source}"]
    used_ranges: list[range] = []
    for _score, index in sorted(scored_lines, reverse=True):
        start = max(0, index - 2)
        end = min(len(lines), index + 3)
        current_range = range(start, end)
        if any(set(current_range).intersection(used) for used in used_ranges):
            continue
        used_ranges.append(current_range)
        excerpt_lines = []
        for line_number in current_range:
            marker = ">" if line_number == index else " "
            excerpt_lines.append(f"{marker} {line_number + 1}: {lines[line_number]}")
        excerpts.append("\n".join(excerpt_lines))
        if len(excerpts) > max_results:
            break

    return _bounded_text("\n\n".join(excerpts), A2A_DOCS_MAX_SEARCH_CHARS)


def create_a2a_docs_tools() -> list[FunctionTool]:
    """Create local function tools for A2A protocol documentation lookup."""
    return [
        FunctionTool(fetch_a2a_protocol_docs),
        FunctionTool(search_a2a_protocol_docs),
    ]


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

You have access to Handler's hosted documentation through an MCP server and to A2A protocol documentation through local documentation search/fetch tools backed by the official A2A protocol site's llms text files. Use these tools when answering Handler-specific or A2A-specific questions about commands, configuration, workflows, authentication, MCP, local servers, tasks, messages, artifacts, streaming, or troubleshooting. Prefer current documentation over memory, and cite the relevant page, source, or command when helpful.

Handler's architecture consists of:
1. **TUI** - An interactive terminal interface (Textual-based) for managing agent connections, sending messages, and viewing streaming responses
2. **CLI** - A rich-click powered command-line interface for scripting and automation
3. **A2AService** - A unified service layer wrapping the a2a-sdk for protocol operations
4. **Server Agent** - A local A2A-compatible agent (you!) for testing, built with Google ADK
5. **MCP Server** - A bridge that exposes Handler's A2A operations as agent-friendly tools

Handler supports streaming responses, push notifications, session persistence, and both JSON and formatted text output.

When users want to operate on another A2A agent, explain the Handler CLI/TUI/MCP path and provide concrete commands such as `handler card get`, `handler message send`, `handler task get`, or `handler mcp` where appropriate.

Format answers as concise Markdown so Handler's TUI can render them richly. Use short headings, bullets or numbered steps, inline code for commands and configuration keys, fenced code blocks for shell/TOML/JSON/Python examples, and links to relevant documentation pages when the docs tools provide them.

Be conversational, helpful, concise, and practical."""

    tools = []
    if _handler_docs_mcp_enabled():
        tools.append(create_handler_docs_toolset())
    else:
        logger.info("Handler docs MCP toolset disabled by HANDLER_DOCS_MCP_ENABLED")
    if _a2a_docs_tools_enabled():
        tools.extend(create_a2a_docs_tools())
    else:
        logger.info("A2A docs tools disabled by A2A_DOCS_TOOLS_ENABLED")

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
