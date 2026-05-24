"""Agent card building and configuration."""

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    APIKeySecurityScheme,
    In,
    SecurityScheme,
)
from google.adk.agents.llm_agent import Agent

from a2a_handler.common import get_logger

logger = get_logger(__name__)


def build_agent_card(
    agent: Agent,
    host: str,
    port: int,
    require_auth: bool = False,
) -> AgentCard:
    """Build an AgentCard with streaming and push notification capabilities.

    Args:
        agent: The ADK agent
        host: Host address for the RPC URL
        port: Port number for the RPC URL
        require_auth: Whether to require API key authentication

    Returns:
        Configured AgentCard with capabilities enabled
    """
    agent_capabilities = AgentCapabilities(
        streaming=True,
        push_notifications=True,
    )

    skills = [
        AgentSkill(
            id="handler_assistant",
            name="Handler Assistant",
            description=(
                "Answers Handler usage questions with documentation-backed help "
                "for CLI commands, TUI workflows, MCP, local servers, auth, "
                "configuration, and troubleshooting"
            ),
            tags=["handler", "cli", "tui", "mcp", "docs", "help", "auth"],
            examples=[
                "How do I send a message with Handler?",
                "What CLI commands are available?",
                "How do I validate an agent card?",
                "How do I expose Handler as an MCP server?",
            ],
        ),
        AgentSkill(
            id="a2a_protocol_reference",
            name="A2A Protocol Reference",
            description=(
                "Looks up official A2A protocol documentation for concepts such "
                "as agent cards, messages, tasks, artifacts, streaming, push "
                "notifications, and the relationship between A2A and MCP"
            ),
            tags=[
                "a2a",
                "protocol",
                "agent-card",
                "messages",
                "tasks",
                "artifacts",
                "streaming",
                "docs",
            ],
            examples=[
                "What is the difference between A2A messages and tasks?",
                "How do A2A artifacts work?",
                "What should an agent card include?",
                "How does A2A streaming work?",
            ],
        ),
        AgentSkill(
            id="handler_source_reference",
            name="Handler Source Reference",
            description=(
                "Searches the locally installed Handler package source to explain "
                "implementation details that are not obvious from the docs"
            ),
            tags=[
                "handler",
                "source",
                "implementation",
                "python",
                "textual",
                "adk",
                "debugging",
            ],
            examples=[
                "Where is Handler's TUI loading indicator implemented?",
                "How does Handler start the embedded agent?",
                "Where does Handler render task artifacts?",
                "How does Handler connect to A2A servers?",
            ],
        ),
    ]

    display_host = "localhost" if host == "0.0.0.0" else host
    rpc_endpoint_url = f"http://{display_host}:{port}/"

    logger.debug("Building agent card with RPC URL: %s", rpc_endpoint_url)

    security_schemes: dict[str, SecurityScheme] | None = None
    security: list[dict[str, list[str]]] | None = None

    if require_auth:
        api_key_scheme = SecurityScheme(
            root=APIKeySecurityScheme(
                type="apiKey",
                name="X-API-Key",
                in_=In.header,
            )
        )
        security_schemes = {"apiKey": api_key_scheme}
        security = [{"apiKey": []}]
        logger.info("API key authentication enabled")

    return AgentCard(
        name=agent.name,
        description=agent.description or "Handler A2A agent",
        url=rpc_endpoint_url,
        version="1.0.0",
        capabilities=agent_capabilities,
        skills=skills,
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        security_schemes=security_schemes,
        security=security,
    )
