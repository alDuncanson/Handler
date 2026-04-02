"""LLM agent creation and configuration."""

import os

from google.adk.agents.llm_agent import Agent
from google.adk.models.lite_llm import LiteLlm

from a2a_handler.common import get_logger
from a2a_handler.common.dotenv import load_runtime_dotenv

logger = get_logger(__name__)

DEFAULT_OLLAMA_API_BASE = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:1b"


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


def create_llm_agent(model: str | None = None) -> Agent:
    """Create and configure the A2A agent using Ollama via LiteLLM.

    Args:
        model: Ollama model identifier (e.g., 'llama3.2:1b')

    Returns:
        Configured ADK Agent instance
    """
    language_model = create_language_model(model)

    instruction = """You are Handler's Agent, the built-in assistant for the Handler application.

Handler is an A2A protocol client published on PyPI as `a2a-handler`. It provides tools for developers to communicate with, test, and debug A2A-compatible agents.

Handler's architecture consists of:
1. **TUI** - An interactive terminal interface (Textual-based) for managing agent connections, sending messages, and viewing streaming responses
2. **CLI** - A rich-click powered command-line interface for scripting and automation
3. **A2AService** - A unified service layer wrapping the a2a-sdk for protocol operations
4. **Server Agent** - A local A2A-compatible agent (you!) for testing, built with Google ADK

Handler supports streaming responses, push notifications, session persistence, and both JSON and formatted text output.

Be conversational, helpful, and concise."""

    agent = Agent(
        name="Handler",
        model=language_model,
        description="Handler's built-in assistant for testing and development",
        instruction=instruction,
    )

    logger.info("Agent created successfully: %s", agent.name)
    return agent
