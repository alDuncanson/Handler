"""Agent card building and configuration."""

from importlib.metadata import version as package_version

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    APIKeySecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import (
    PROTOCOL_VERSION_0_3,
    PROTOCOL_VERSION_1_0,
    TransportProtocol,
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

    The card advertises both A2A v1.0 and v0.3 JSON-RPC interfaces so that
    both current and legacy clients can connect to the built-in server.

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

    # Advertise both protocol versions on the same JSON-RPC endpoint so v0.3
    # clients keep working alongside v1.0 clients.
    supported_interfaces = [
        AgentInterface(
            url=rpc_endpoint_url,
            protocol_binding=TransportProtocol.JSONRPC.value,
            protocol_version=PROTOCOL_VERSION_1_0,
        ),
        AgentInterface(
            url=rpc_endpoint_url,
            protocol_binding=TransportProtocol.JSONRPC.value,
            protocol_version=PROTOCOL_VERSION_0_3,
        ),
    ]

    card_kwargs: dict = {
        "name": agent.name,
        "description": agent.description or "Handler A2A agent",
        "version": package_version("a2a-handler"),
        "supported_interfaces": supported_interfaces,
        "capabilities": agent_capabilities,
        "skills": skills,
        "default_input_modes": ["text/plain"],
        "default_output_modes": ["text/plain"],
    }

    if require_auth:
        card_kwargs["security_schemes"] = {
            "apiKey": SecurityScheme(
                api_key_security_scheme=APIKeySecurityScheme(
                    name="X-API-Key",
                    location="header",
                )
            )
        }
        card_kwargs["security_requirements"] = [
            SecurityRequirement(schemes={"apiKey": StringList()})
        ]
        logger.info("API key authentication enabled")

    return AgentCard(**card_kwargs)
