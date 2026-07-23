"""A2A application setup and middleware."""

import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.types import AgentCard, TaskPushNotificationConfig
from a2a.utils.errors import InvalidParamsError
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.agents.llm_agent import Agent
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import (
    InMemoryCredentialService,
)
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    reject_control_chars,
    validate_resource_id,
    validate_webhook_url,
)

logger = get_logger(__name__)

DEFAULT_HTTP_TIMEOUT_SECONDS = 30


class ValidatingPushNotificationConfigStore(InMemoryPushNotificationConfigStore):
    """Push config store that rejects malformed callback targets."""

    async def set_info(
        self,
        task_id: str,
        notification_config: TaskPushNotificationConfig,
        context: ServerCallContext,
    ) -> None:
        """Validate webhook settings before storing push configuration."""
        try:
            validate_resource_id(task_id, "task_id")
            validate_webhook_url(notification_config.url)
            if notification_config.token:
                reject_control_chars(notification_config.token, "webhook_token")
        except InputValidationError as error:
            raise InvalidParamsError(
                message=f"{error.code}: {error.message}",
            ) from error

        await super().set_info(task_id, notification_config, context)


def generate_api_key() -> str:
    """Generate a secure random API key.

    Returns:
        A URL-safe random string suitable for use as an API key
    """
    return secrets.token_urlsafe(32)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce API key authentication on A2A endpoints."""

    OPEN_PATHS = {
        "/.well-known/agent-card.json",
        "/.well-known/agent.json",
        "/health",
    }

    def __init__(self, app: Starlette, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.OPEN_PATHS:
            return await call_next(request)

        if request.method == "GET" and request.url.path == "/":
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        api_key_header = request.headers.get("X-API-Key")

        authenticated = False

        if api_key_header and api_key_header == self.api_key:
            authenticated = True
        elif auth_header:
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                if token == self.api_key:
                    authenticated = True
            elif auth_header.startswith("ApiKey "):
                token = auth_header[7:]
                if token == self.api_key:
                    authenticated = True

        if not authenticated:
            return JSONResponse(
                status_code=401,
                content={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32000,
                        "message": "Unauthorized: Invalid or missing API key",
                    },
                    "id": None,
                },
                headers={"WWW-Authenticate": 'ApiKey realm="Handler Server"'},
            )

        return await call_next(request)


def create_runner_factory(agent: Agent) -> Callable[[], Awaitable[Runner]]:
    """Create a factory function that builds a Runner for the agent.

    Args:
        agent: The ADK agent to wrap

    Returns:
        A callable that creates a Runner instance
    """

    async def create_runner() -> Runner:
        return Runner(
            app_name=agent.name or "handler_agent",
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
            credential_service=InMemoryCredentialService(),
        )

    return create_runner


def create_a2a_application(
    agent: Agent,
    agent_card: AgentCard,
    api_key: str | None = None,
) -> Starlette:
    """Create a Starlette A2A application with full push notification support.

    This is a custom implementation that replaces google-adk's to_a2a() to add
    push notification support. The to_a2a() function doesn't pass push_config_store
    or push_sender to DefaultRequestHandler, causing push notification operations
    to fail with "UnsupportedOperationError".

    Args:
        agent: The ADK agent
        agent_card: Pre-configured agent card
        api_key: Optional API key for authentication

    Returns:
        Configured Starlette application
    """
    task_store = InMemoryTaskStore()
    push_notification_config_store = ValidatingPushNotificationConfigStore()
    http_client = httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
    push_notification_sender = BasePushNotificationSender(
        http_client, push_notification_config_store
    )

    agent_executor = A2aAgentExecutor(
        runner=create_runner_factory(agent),
    )

    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=task_store,
        agent_card=agent_card,
        push_config_store=push_notification_config_store,
        push_sender=push_notification_sender,
    )

    middleware: list[Middleware] = []
    if api_key:
        middleware.append(
            Middleware(APIKeyAuthMiddleware, api_key=api_key)  # type: ignore[arg-type]
        )

    # Serve the agent card plus a JSON-RPC endpoint. ``enable_v0_3_compat``
    # lets legacy v0.3 clients call the same endpoint as v1.0 clients.
    routes = [
        *create_agent_card_routes(agent_card),
        *create_jsonrpc_routes(request_handler, rpc_url="/", enable_v0_3_compat=True),
    ]
    logger.info("A2A routes configured with push notification support")

    async def cleanup_http_client() -> None:
        await http_client.aclose()
        logger.info("HTTP client closed")

    @asynccontextmanager
    async def lifespan(application: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await cleanup_http_client()

    application = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)

    return application
