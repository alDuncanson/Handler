"""MCP server implementation exposing A2A capabilities as tools and resources."""

from typing import Literal

import httpx
from mcp.server.fastmcp import FastMCP

from a2a_handler.auth import AuthCredentials, create_api_key_auth, create_bearer_auth
from a2a_handler.common import get_logger
from a2a_handler.service import A2AService
from a2a_handler.session import (
    clear_credentials as session_clear_credentials,
)
from a2a_handler.session import (
    clear_session,
    get_credentials,
    get_session,
    get_session_store,
    set_credentials,
    update_session,
)
from a2a_handler.validation import (
    ValidationResult,
    validate_agent_card_from_file,
    validate_agent_card_from_url,
)

logger = get_logger(__name__)

TIMEOUT = 120


def _build_http_client(timeout: int = TIMEOUT) -> httpx.AsyncClient:
    """Build an HTTP client with the specified timeout."""
    return httpx.AsyncClient(timeout=timeout)


def _resolve_credentials(
    agent_url: str,
    bearer_token: str | None = None,
    api_key: str | None = None,
) -> AuthCredentials | None:
    """Resolve credentials from explicit args or saved session."""
    if bearer_token:
        return create_bearer_auth(bearer_token)
    if api_key:
        return create_api_key_auth(api_key)
    return get_credentials(agent_url)


def create_mcp_server() -> FastMCP:
    """Create and configure the MCP server with A2A tools."""
    mcp = FastMCP(
        name="Handler",
        instructions=(
            "Handler exposes A2A (Agent-to-Agent) protocol capabilities. "
            "Use these tools to interact with A2A agents, validate agent cards, "
            "and discover agent capabilities."
        ),
        website_url="https://github.com/alDuncanson/handler",
    )

    @mcp.tool()
    async def validate_agent_card(
        source: str,
        from_file: bool = False,
    ) -> dict:
        """Validate an A2A agent card from a URL or local file.

        Use this tool to check if an agent card is valid according to the A2A protocol.
        The agent card contains metadata about an agent's capabilities, supported
        content types, and authentication requirements.

        Args:
            source: URL of the agent (e.g., "http://localhost:8000") or path to a
                   local JSON file containing the agent card.
            from_file: If True, treat source as a file path. If False (default),
                      treat source as an agent URL.

        Returns:
            A dictionary containing:
            - valid: Whether the agent card is valid
            - agent_name: Name of the agent (if available)
            - protocol_version: A2A protocol version
            - issues: List of validation issues (if any)
        """
        logger.info("Validating agent card from %s", source)

        result: ValidationResult
        if from_file:
            result = validate_agent_card_from_file(source)
        else:
            result = await validate_agent_card_from_url(source)

        response: dict = {
            "valid": result.valid,
            "source": result.source,
            "source_type": result.source_type.value,
            "agent_name": result.agent_name,
            "protocol_version": result.protocol_version,
        }

        if result.issues:
            response["issues"] = [
                {
                    "field": issue.field_name,
                    "message": issue.message,
                    "type": issue.issue_type,
                }
                for issue in result.issues
            ]

        if result.agent_card:
            response["capabilities"] = {
                "streaming": result.agent_card.capabilities.streaming
                if result.agent_card.capabilities
                else False,
                "push_notifications": result.agent_card.capabilities.push_notifications
                if result.agent_card.capabilities
                else False,
            }
            if result.agent_card.skills:
                response["skills"] = [
                    {"id": skill.id, "name": skill.name}
                    for skill in result.agent_card.skills
                ]

        return response

    @mcp.tool()
    async def get_agent_card(agent_url: str) -> dict:
        """Retrieve an agent's card with full details.

        Fetches the agent card from the specified A2A agent URL. The agent card
        contains metadata about the agent including its name, description,
        capabilities, skills, and supported content types.

        Args:
            agent_url: Base URL of the A2A agent (e.g., "http://localhost:8000")

        Returns:
            The agent card as a dictionary with all available fields.
        """
        logger.info("Getting agent card from %s", agent_url)

        async with _build_http_client() as http_client:
            service = A2AService(http_client, agent_url)
            card = await service.get_card()

            return card.model_dump(exclude_none=True)

    @mcp.tool()
    async def send_message(
        agent_url: str,
        message: str,
        context_id: str | None = None,
        task_id: str | None = None,
        use_session: bool = False,
        bearer_token: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        """Send a message to an A2A agent and receive a response.

        This is the primary way to interact with A2A agents. Send a text message
        and receive the agent's response. Use context_id and task_id for
        conversation continuity.

        Args:
            agent_url: Base URL of the A2A agent (e.g., "http://localhost:8000")
            message: The text message to send to the agent
            context_id: Optional context ID for conversation continuity
            task_id: Optional task ID to continue an existing task
            use_session: If True, use saved session context (context_id/task_id)
            bearer_token: Optional bearer token for authentication
            api_key: Optional API key for authentication

        Returns:
            A dictionary containing:
            - context_id: Context ID for follow-up messages
            - task_id: Task ID for task operations
            - state: Current task state (e.g., "completed", "working", "input-required")
            - text: The agent's response text
            - needs_input: Whether the agent needs more input
            - needs_auth: Whether authentication is required
        """
        logger.info("Sending message to %s", agent_url)

        if use_session and not context_id:
            session = get_session(agent_url)
            if session.context_id:
                context_id = session.context_id
                logger.info("Using saved context: %s", context_id)

        credentials = _resolve_credentials(agent_url, bearer_token, api_key)

        async with _build_http_client() as http_client:
            service = A2AService(
                http_client,
                agent_url,
                credentials=credentials,
            )

            result = await service.send(message, context_id, task_id)
            update_session(agent_url, result.context_id, result.task_id)

            return {
                "context_id": result.context_id,
                "task_id": result.task_id,
                "state": result.state.value if result.state else None,
                "text": result.text,
                "needs_input": result.needs_input,
                "needs_auth": result.needs_auth,
            }

    @mcp.tool()
    async def get_task(
        agent_url: str,
        task_id: str,
        history_length: int | None = None,
        bearer_token: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        """Get the current status and details of a task.

        Retrieves the current state of a task from an A2A agent, optionally
        including conversation history.

        Args:
            agent_url: Base URL of the A2A agent
            task_id: ID of the task to retrieve
            history_length: Optional number of history messages to include
            bearer_token: Optional bearer token for authentication
            api_key: Optional API key for authentication

        Returns:
            A dictionary containing:
            - task_id: The task ID
            - context_id: The context ID
            - state: Current task state
            - text: Response text from artifacts or history
        """
        logger.info("Getting task %s from %s", task_id, agent_url)

        credentials = _resolve_credentials(agent_url, bearer_token, api_key)

        async with _build_http_client() as http_client:
            service = A2AService(http_client, agent_url, credentials=credentials)
            result = await service.get_task(task_id, history_length)

            return {
                "task_id": result.task_id,
                "context_id": result.context_id,
                "state": result.state.value,
                "text": result.text,
            }

    @mcp.tool()
    async def cancel_task(
        agent_url: str,
        task_id: str,
        bearer_token: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        """Cancel a running task.

        Requests cancellation of a task that is currently in progress.

        Args:
            agent_url: Base URL of the A2A agent
            task_id: ID of the task to cancel
            bearer_token: Optional bearer token for authentication
            api_key: Optional API key for authentication

        Returns:
            A dictionary containing:
            - task_id: The task ID
            - context_id: The context ID
            - state: Updated task state (should be "canceled")
            - text: Any final response text
        """
        logger.info("Canceling task %s at %s", task_id, agent_url)

        credentials = _resolve_credentials(agent_url, bearer_token, api_key)

        async with _build_http_client() as http_client:
            service = A2AService(http_client, agent_url, credentials=credentials)
            result = await service.cancel_task(task_id)

            return {
                "task_id": result.task_id,
                "context_id": result.context_id,
                "state": result.state.value,
                "text": result.text,
            }

    @mcp.tool()
    async def set_task_notification(
        agent_url: str,
        task_id: str,
        webhook_url: str,
        webhook_token: str | None = None,
        bearer_token: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        """Configure push notifications for a task.

        Sets up a webhook URL to receive push notifications when the task
        status changes. This allows for async notification instead of polling.

        Args:
            agent_url: Base URL of the A2A agent
            task_id: ID of the task to configure notifications for
            webhook_url: URL that will receive notification POSTs
            webhook_token: Optional authentication token for the webhook
            bearer_token: Optional bearer token for agent authentication
            api_key: Optional API key for agent authentication

        Returns:
            A dictionary containing:
            - task_id: The task ID
            - url: The configured webhook URL
            - token: The webhook token (truncated for security)
            - config_id: The notification config ID (if provided by agent)
        """
        logger.info("Setting push config for task %s at %s", task_id, agent_url)

        credentials = _resolve_credentials(agent_url, bearer_token, api_key)

        async with _build_http_client() as http_client:
            service = A2AService(http_client, agent_url, credentials=credentials)
            config = await service.set_push_config(task_id, webhook_url, webhook_token)

            result: dict = {"task_id": config.task_id}
            if config.push_notification_config:
                pnc = config.push_notification_config
                result["url"] = pnc.url
                if pnc.token:
                    result["token"] = f"{pnc.token[:20]}..."
                if pnc.id:
                    result["config_id"] = pnc.id

            return result

    @mcp.tool()
    async def get_task_notification(
        agent_url: str,
        task_id: str,
        config_id: str | None = None,
        bearer_token: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        """Get the push notification configuration for a task.

        Retrieves the current push notification webhook configuration for a task.

        Args:
            agent_url: Base URL of the A2A agent
            task_id: ID of the task
            config_id: Optional specific config ID to retrieve
            bearer_token: Optional bearer token for authentication
            api_key: Optional API key for authentication

        Returns:
            A dictionary containing:
            - task_id: The task ID
            - url: The configured webhook URL
            - token: The webhook token (truncated for security)
            - config_id: The notification config ID
        """
        logger.info("Getting push config for task %s at %s", task_id, agent_url)

        credentials = _resolve_credentials(agent_url, bearer_token, api_key)

        async with _build_http_client() as http_client:
            service = A2AService(http_client, agent_url, credentials=credentials)
            config = await service.get_push_config(task_id, config_id)

            result: dict = {"task_id": config.task_id}
            if config.push_notification_config:
                pnc = config.push_notification_config
                result["url"] = pnc.url
                if pnc.token:
                    result["token"] = f"{pnc.token[:20]}..."
                if pnc.id:
                    result["config_id"] = pnc.id

            return result

    @mcp.tool()
    async def list_sessions() -> dict:
        """List all saved sessions.

        Sessions store context_id, task_id, and credentials for agents you've
        interacted with. This allows for conversation continuity across
        multiple interactions.

        Returns:
            A dictionary containing:
            - count: Number of saved sessions
            - sessions: List of sessions with agent_url, context_id, task_id,
                       and has_credentials flag
        """
        logger.info("Listing all sessions")

        store = get_session_store()
        sessions = store.list_all()

        return {
            "count": len(sessions),
            "sessions": [
                {
                    "agent_url": s.agent_url,
                    "context_id": s.context_id,
                    "task_id": s.task_id,
                    "has_credentials": s.credentials is not None,
                }
                for s in sessions
            ],
        }

    @mcp.tool()
    async def get_session_info(agent_url: str) -> dict:
        """Get session information for a specific agent.

        Retrieves the saved session state for an agent, including context_id
        and task_id for conversation continuity.

        Args:
            agent_url: Base URL of the A2A agent

        Returns:
            A dictionary containing:
            - agent_url: The agent URL
            - context_id: Saved context ID (or None)
            - task_id: Saved task ID (or None)
            - has_credentials: Whether credentials are saved
        """
        logger.info("Getting session for %s", agent_url)

        session = get_session(agent_url)

        return {
            "agent_url": session.agent_url,
            "context_id": session.context_id,
            "task_id": session.task_id,
            "has_credentials": session.credentials is not None,
        }

    @mcp.tool()
    async def clear_session_data(agent_url: str | None = None) -> dict:
        """Clear saved session data.

        Removes saved session state (context_id, task_id) for an agent or all
        agents. Does not clear credentials - use clear_agent_credentials for that.

        Args:
            agent_url: URL of agent to clear. If None, clears ALL sessions.

        Returns:
            A dictionary containing:
            - cleared: Description of what was cleared
        """
        if agent_url:
            logger.info("Clearing session for %s", agent_url)
            clear_session(agent_url)
            return {"cleared": f"Session for {agent_url}"}
        else:
            logger.info("Clearing all sessions")
            clear_session()
            return {"cleared": "All sessions"}

    @mcp.tool()
    async def set_agent_credentials(
        agent_url: str,
        bearer_token: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        """Set authentication credentials for an agent.

        Saves credentials that will be used for all future requests to this
        agent. Either bearer_token or api_key should be provided, not both.

        Args:
            agent_url: Base URL of the A2A agent
            bearer_token: Bearer token for Authorization header
            api_key: API key for X-API-Key header

        Returns:
            A dictionary containing:
            - agent_url: The agent URL
            - auth_type: Type of auth configured ("bearer" or "api_key")
        """
        logger.info("Setting credentials for %s", agent_url)

        if bearer_token:
            credentials = create_bearer_auth(bearer_token)
            set_credentials(agent_url, credentials)
            return {"agent_url": agent_url, "auth_type": "bearer"}
        elif api_key:
            credentials = create_api_key_auth(api_key)
            set_credentials(agent_url, credentials)
            return {"agent_url": agent_url, "auth_type": "api_key"}
        else:
            return {"error": "Either bearer_token or api_key must be provided"}

    @mcp.tool()
    async def clear_agent_credentials(agent_url: str) -> dict:
        """Clear saved credentials for an agent.

        Removes any saved authentication credentials for the specified agent.

        Args:
            agent_url: Base URL of the A2A agent

        Returns:
            A dictionary containing:
            - agent_url: The agent URL
            - cleared: True if credentials were cleared
        """
        logger.info("Clearing credentials for %s", agent_url)

        session_clear_credentials(agent_url)

        return {"agent_url": agent_url, "cleared": True}

    return mcp


def run_mcp_server(
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
) -> None:
    """Run the MCP server with the specified transport.

    Args:
        transport: The transport protocol to use. Supported values:
                  - "stdio": Standard input/output (default, for CLI integration)
                  - "sse": Server-Sent Events (for HTTP clients)
    """
    mcp = create_mcp_server()
    logger.info("Starting MCP server with %s transport", transport)
    mcp.run(transport=transport)


if __name__ == "__main__":
    run_mcp_server()
