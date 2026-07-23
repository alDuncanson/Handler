"""A2A server agent with streaming and push notifications.

Provides a local A2A-compatible agent server for testing and development.
"""

import asyncio
import os

import uvicorn

from a2a_handler.common import get_logger, setup_logging

from .agent import DEFAULT_OLLAMA_MODEL, create_llm_agent
from .app import create_a2a_application, generate_api_key
from .card import build_agent_card
from .ollama import check_ollama_model, prompt_ollama_pull

setup_logging(level="INFO")
logger = get_logger(__name__)


def run_server(
    host: str,
    port: int,
    require_auth: bool = False,
    api_key: str | None = None,
    model: str | None = None,
) -> None:
    """Start the A2A server agent.

    Args:
        host: Host address to bind to
        port: Port number to bind to
        require_auth: Whether to require API key authentication
        api_key: Specific API key to use (generated if not provided and auth required)
        model: Ollama model identifier (e.g., 'gemma4:e2b')
    """
    effective_model = model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)

    if not check_ollama_model(effective_model):
        if not prompt_ollama_pull(effective_model):
            return

    print(f"\nStarting Handler server on {host}:{port}\n")
    logger.info("Initializing A2A server with push notification support...")

    effective_api_key = None
    if require_auth:
        effective_api_key = (
            api_key or os.getenv("HANDLER_API_KEY") or generate_api_key()
        )
        print(
            f"Authentication required!\n"
            f"API Key: {effective_api_key}\n"
            f"\nUse with Handler CLI:\n"
            f'  handler message send http://localhost:{port} "message" '
            f"--api-key {effective_api_key}\n"
        )

    agent = create_llm_agent(model=effective_model)
    agent_card = build_agent_card(agent, host, port, require_auth=require_auth)

    streaming_enabled = bool(agent_card.capabilities.streaming)
    push_notifications_enabled = bool(agent_card.capabilities.push_notifications)
    auth_enabled = bool(agent_card.security_schemes)

    logger.info(
        "Agent card capabilities: streaming=%s, push_notifications=%s, auth=%s",
        streaming_enabled,
        push_notifications_enabled,
        auth_enabled,
    )

    a2a_application = create_a2a_application(agent, agent_card, effective_api_key)

    config = uvicorn.Config(a2a_application, host=host, port=port)
    server = uvicorn.Server(config)

    asyncio.run(server.serve())
