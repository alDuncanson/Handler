"""A2A protocol service layer.

Provides a unified interface for A2A operations, shared between the CLI and TUI.
"""

import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Union

import httpx
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.client.errors import A2AClientHTTPError
from a2a.types import (
    AgentCard,
    GetTaskPushNotificationConfigParams,
    Message,
    Part,
    PushNotificationConfig,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskIdParams,
    TaskPushNotificationConfig,
    TaskQueryParams,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
    TransportProtocol,
)

from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    PREV_AGENT_CARD_WELL_KNOWN_PATH,
)

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    reject_control_chars,
    validate_agent_url,
    validate_resource_id,
    validate_webhook_url,
)

logger = get_logger(__name__)

TERMINAL_TASK_STATES = {
    TaskState.completed,
    TaskState.canceled,
    TaskState.failed,
    TaskState.rejected,
}


@dataclass
class StreamEvent:
    """A single event from a streaming response.

    This is a Handler convenience wrapper around SDK streaming event types.
    The original SDK event is accessible via `status` or `artifact` fields.
    """

    event_type: str
    task: Task | None = None
    message: Message | None = None
    status: TaskStatusUpdateEvent | None = None
    artifact: TaskArtifactUpdateEvent | None = None
    text: str = ""

    @property
    def context_id(self) -> str | None:
        """Get context_id from the underlying SDK type."""
        if self.task:
            return self.task.context_id
        if self.message:
            return self.message.context_id
        if self.status:
            return self.status.context_id
        if self.artifact:
            return self.artifact.context_id
        return None

    @property
    def task_id(self) -> str | None:
        """Get task_id from the underlying SDK type."""
        if self.task:
            return self.task.id
        if self.message:
            return self.message.task_id
        if self.status:
            return self.status.task_id
        if self.artifact:
            return self.artifact.task_id
        return None

    @property
    def state(self) -> TaskState | None:
        """Get task state from the underlying SDK type."""
        if self.task and self.task.status:
            return self.task.status.state
        if self.status and self.status.status:
            return self.status.status.state
        return None


def extract_text_from_message_parts(message_parts: list[Part] | None) -> str:
    """Extract text content from message parts."""
    if not message_parts:
        return ""

    extracted_texts = []
    for part in message_parts:
        if isinstance(part.root, TextPart):
            extracted_texts.append(part.root.text)

    return "\n".join(text for text in extracted_texts if text)


def extract_text_from_task(task: Task) -> str:
    """Extract text from task artifacts, falling back to history if no artifacts."""
    extracted_texts = []

    if task.artifacts:
        for artifact in task.artifacts:
            if artifact.parts:
                extracted_texts.append(extract_text_from_message_parts(artifact.parts))

    # Only check history if no artifacts found (avoids duplication)
    if not extracted_texts and task.history:
        for message in task.history:
            if message.role == Role.agent and message.parts:
                extracted_texts.append(extract_text_from_message_parts(message.parts))

    return "\n".join(text for text in extracted_texts if text)


A2AResponse = Union[Task, Message]


def response_context_id(response: A2AResponse) -> str | None:
    """Get context_id from a Task or Message."""
    return response.context_id


def response_task_id(response: A2AResponse) -> str | None:
    """Get task_id from a Task or Message."""
    if isinstance(response, Task):
        return response.id
    return response.task_id


def response_state(response: A2AResponse) -> TaskState | None:
    """Get task state from a Task or Message (Messages have no state)."""
    if isinstance(response, Task) and response.status:
        return response.status.state
    return None


def is_terminal(response: A2AResponse) -> bool:
    """Check if the response reached a terminal state."""
    state = response_state(response)
    return state in TERMINAL_TASK_STATES if state else False


def response_needs_auth(response: A2AResponse) -> bool:
    """Check if the response requires authentication."""
    return response_state(response) == TaskState.auth_required


def extract_text(response: A2AResponse) -> str:
    """Extract text content from a Task or Message."""
    if isinstance(response, Task):
        return extract_text_from_task(response)
    return extract_text_from_message_parts(response.parts)


def protocol_dump(response: A2AResponse) -> dict[str, object]:
    """Serialize an A2A protocol object to a JSON-compatible dict."""
    return response.model_dump(mode="json", exclude_none=True)


def _truncate_secret(value: str) -> str:
    """Return a short preview for secrets without exposing the full value."""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def push_config_dump(config: TaskPushNotificationConfig) -> dict[str, object]:
    """Serialize push-config data while redacting webhook auth tokens."""
    data = config.model_dump(mode="json", exclude_none=True)
    push_notification_config = data.get("pushNotificationConfig")
    if not isinstance(push_notification_config, dict):
        return data

    token = push_notification_config.get("token")
    if not isinstance(token, str) or not token:
        return data

    redacted_config = dict(push_notification_config)
    redacted_config["token"] = _truncate_secret(token)
    redacted = dict(data)
    redacted["pushNotificationConfig"] = redacted_config
    return redacted


class A2AService:
    """High-level service for A2A protocol operations.

    Wraps the a2a-sdk Client and provides a simplified interface
    for common operations. Designed to be shared between CLI and TUI.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        agent_url: str,
        enable_streaming: bool = True,
        push_notification_url: str | None = None,
        push_notification_token: str | None = None,
        credentials: AuthCredentials | None = None,
    ) -> None:
        """Initialize the A2A service.

        Args:
            http_client: Async HTTP client to use for requests
            agent_url: Base URL of the A2A agent
            enable_streaming: Whether to prefer streaming when available
            push_notification_url: Optional webhook URL for push notifications
            push_notification_token: Optional token for push notification auth
            credentials: Optional authentication credentials
        """
        validate_agent_url(agent_url)
        if push_notification_url:
            validate_webhook_url(push_notification_url)
        if push_notification_token:
            reject_control_chars(push_notification_token, "push_notification_token")

        self.http_client = http_client
        self.agent_url = agent_url
        self.enable_streaming = enable_streaming
        self.push_notification_url = push_notification_url
        self.push_notification_token = push_notification_token
        self.credentials = credentials
        self._cached_client: Client | None = None
        self._cached_agent_card: AgentCard | None = None
        self._applied_auth_headers: set[str] = set()

        if credentials:
            self.set_credentials(credentials)

    def set_credentials(self, credentials: AuthCredentials) -> None:
        """Set or update authentication credentials.

        Args:
            credentials: Authentication credentials to apply
        """
        for header_name in self._applied_auth_headers:
            self.http_client.headers.pop(header_name, None)
        self._applied_auth_headers.clear()

        self.credentials = credentials
        self._cached_client = None

        auth_headers = credentials.to_headers()
        if auth_headers:
            self.http_client.headers.update(auth_headers)
            self._applied_auth_headers = set(auth_headers.keys())

        if credentials.auth_type == AuthType.MTLS:
            logger.debug("mTLS credentials set (transport-level authentication)")
        elif credentials.auth_type == AuthType.OAUTH2:
            logger.debug(
                "OAuth2 credentials set (token will be fetched on first request)"
            )
        else:
            logger.debug(
                "Applied authentication headers: %s", list(auth_headers.keys())
            )

    async def ensure_oauth2_token(self) -> None:
        """Fetch or refresh the OAuth2 access token if needed.

        Acquires a new token when no token is present or when the cached
        token has expired (or is about to expire within a safety margin).
        """
        if self.credentials is None or self.credentials.auth_type != AuthType.OAUTH2:
            return
        if not self.credentials.is_token_expired():
            return
        if self.credentials.value:
            logger.info("OAuth2 access token expired, refreshing")
            self.credentials.clear_token()
        else:
            logger.info(
                "Fetching OAuth2 access token from %s", self.credentials.token_url
            )
        await self.credentials.fetch_oauth2_token()
        auth_headers = self.credentials.to_headers()
        self.http_client.headers.update(auth_headers)
        self._applied_auth_headers = set(auth_headers.keys())
        self._cached_client = None
        logger.info("OAuth2 access token applied")

    def clear_credentials(self) -> None:
        """Clear authentication credentials from the service and HTTP client."""
        for header_name in self._applied_auth_headers:
            self.http_client.headers.pop(header_name, None)
        self._applied_auth_headers.clear()
        self.credentials = None
        # Rebuild the SDK client so cleared headers are guaranteed to be used.
        self._cached_client = None
        logger.debug("Cleared authentication headers")

    async def _load_agent_card(self) -> AgentCard:
        """Fetch and cache the agent card without mutating auth state."""
        if self._cached_agent_card is None:
            logger.info("Fetching agent card from %s", self.agent_url)
            card_resolver = A2ACardResolver(self.http_client, self.agent_url)
            try:
                self._cached_agent_card = await card_resolver.get_agent_card()
            except (A2AClientHTTPError, httpx.HTTPStatusError):
                logger.info(
                    "Agent card not found at %s, trying %s",
                    AGENT_CARD_WELL_KNOWN_PATH,
                    PREV_AGENT_CARD_WELL_KNOWN_PATH,
                )
                fallback_resolver = A2ACardResolver(
                    self.http_client,
                    self.agent_url,
                    agent_card_path=PREV_AGENT_CARD_WELL_KNOWN_PATH,
                )
                self._cached_agent_card = await fallback_resolver.get_agent_card()
            logger.info("Connected to agent: %s", self._cached_agent_card.name)
        return self._cached_agent_card

    async def get_card(self) -> AgentCard:
        """Fetch and cache the agent card.

        Tries the standard well-known path first (``agent-card.json``), then
        falls back to the previous path (``agent.json``) used by older ADK
        versions.

        Returns:
            The agent's card with metadata and capabilities
        """
        await self.ensure_oauth2_token()
        return await self._load_agent_card()

    async def _get_or_create_client(self) -> Client:
        """Get or create the A2A client.

        Returns:
            Configured A2A client instance
        """
        await self.ensure_oauth2_token()
        if self._cached_client is None:
            agent_card = await self._load_agent_card()

            push_notification_configs: list[PushNotificationConfig] = []
            if self.push_notification_url:
                push_notification_configs.append(
                    PushNotificationConfig(
                        url=self.push_notification_url,
                        token=self.push_notification_token,
                    )
                )
                logger.info(
                    "Push notification configured: %s", self.push_notification_url
                )

            client_config = ClientConfig(
                httpx_client=self.http_client,
                supported_transports=[TransportProtocol.jsonrpc],
                streaming=self.enable_streaming,
                push_notification_configs=push_notification_configs,
            )

            client_factory = ClientFactory(client_config)
            self._cached_client = client_factory.create(agent_card)
            logger.debug("Created A2A client for %s", agent_card.name)

        return self._cached_client

    @property
    def supports_streaming(self) -> bool:
        """Check if the agent supports streaming."""
        if self._cached_agent_card and self._cached_agent_card.capabilities:
            return bool(self._cached_agent_card.capabilities.streaming)
        return False

    @property
    def supports_push_notifications(self) -> bool:
        """Check if the agent supports push notifications."""
        if self._cached_agent_card and self._cached_agent_card.capabilities:
            return bool(self._cached_agent_card.capabilities.push_notifications)
        return False

    def _build_user_message(
        self,
        message_text: str,
        context_id: str | None = None,
        task_id: str | None = None,
    ) -> Message:
        """Build a user message.

        Args:
            message_text: Message content
            context_id: Optional context ID for conversation continuity
            task_id: Optional task ID to continue

        Returns:
            Properly formatted Message object
        """
        return Message(
            message_id=str(uuid.uuid4()),
            role=Role.user,
            parts=[Part(root=TextPart(text=message_text))],
            context_id=context_id,
            task_id=task_id,
        )

    async def send(
        self,
        message_text: str,
        context_id: str | None = None,
        task_id: str | None = None,
    ) -> Task | Message:
        """Send a message to the agent and wait for completion.

        Returns the raw A2A protocol response (Task or Message).
        """
        client = await self._get_or_create_client()
        user_message = self._build_user_message(message_text, context_id, task_id)

        truncated_message = (
            message_text[:50] if len(message_text) > 50 else message_text
        )
        logger.info("Sending message: %s", truncated_message)

        last_task: Task | None = None
        last_message: Message | None = None

        async for event in client.send_message(user_message):
            if isinstance(event, Message):
                last_message = event
                logger.debug("Received message response")
            elif isinstance(event, tuple):
                received_task, _task_update = event
                last_task = received_task
                logger.debug(
                    "Received task update: %s",
                    received_task.status.state if received_task.status else "unknown",
                )

        response = last_task or last_message
        if response is None:
            raise RuntimeError("A2A send returned neither Task nor Message")

        logger.info(
            "Send complete: task_id=%s, state=%s",
            response_task_id(response),
            response_state(response),
        )
        return response

    async def stream(
        self,
        message_text: str,
        context_id: str | None = None,
        task_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Send a message and stream responses as they arrive.

        Args:
            message_text: Message to send
            context_id: Optional context ID for conversation continuity
            task_id: Optional task ID to continue

        Yields:
            StreamEvent objects as they are received
        """
        client = await self._get_or_create_client()
        user_message = self._build_user_message(message_text, context_id, task_id)

        truncated_message = (
            message_text[:50] if len(message_text) > 50 else message_text
        )
        logger.info("Streaming message: %s", truncated_message)

        async for event in client.send_message(user_message):
            if isinstance(event, Message):
                yield StreamEvent(
                    event_type="message",
                    message=event,
                    text=extract_text_from_message_parts(event.parts),
                )
            elif isinstance(event, tuple):
                received_task, task_update = event
                if isinstance(task_update, TaskStatusUpdateEvent):
                    status_message_text = ""
                    if task_update.status and task_update.status.message:
                        status_message_text = str(task_update.status.message)
                    yield StreamEvent(
                        event_type="status",
                        task=received_task,
                        status=task_update,
                        text=status_message_text,
                    )
                elif isinstance(task_update, TaskArtifactUpdateEvent):
                    artifact_text = ""
                    if task_update.artifact and task_update.artifact.parts:
                        artifact_text = extract_text_from_message_parts(
                            task_update.artifact.parts
                        )
                    yield StreamEvent(
                        event_type="artifact",
                        task=received_task,
                        artifact=task_update,
                        text=artifact_text,
                    )
                else:
                    yield StreamEvent(
                        event_type="task",
                        task=received_task,
                        text=extract_text_from_task(received_task),
                    )

    async def get_task(
        self,
        task_id: str,
        history_length: int | None = None,
    ) -> Task:
        """Get the current state of a task.

        Returns the raw A2A Task object.
        """
        client = await self._get_or_create_client()

        query_params = TaskQueryParams(id=task_id, history_length=history_length)
        logger.info("Getting task: %s", task_id)

        return await client.get_task(query_params)

    async def cancel_task(self, task_id: str) -> Task:
        """Cancel a running task.

        Returns the raw A2A Task object with updated state.
        """
        client = await self._get_or_create_client()

        task_id_params = TaskIdParams(id=task_id)
        logger.info("Canceling task: %s", task_id)

        return await client.cancel_task(task_id_params)

    async def resubscribe(self, task_id: str) -> AsyncIterator[StreamEvent]:
        """Resubscribe to a task's event stream.

        Args:
            task_id: ID of the task to resubscribe to

        Yields:
            StreamEvent objects as they are received
        """
        client = await self._get_or_create_client()

        task_id_params = TaskIdParams(id=task_id)
        logger.info("Resubscribing to task: %s", task_id)

        async for event in client.resubscribe(task_id_params):
            received_task, task_update = event
            if isinstance(task_update, TaskStatusUpdateEvent):
                yield StreamEvent(
                    event_type="status",
                    task=received_task,
                    status=task_update,
                )
            elif isinstance(task_update, TaskArtifactUpdateEvent):
                artifact_text = ""
                if task_update.artifact and task_update.artifact.parts:
                    artifact_text = extract_text_from_message_parts(
                        task_update.artifact.parts
                    )
                yield StreamEvent(
                    event_type="artifact",
                    task=received_task,
                    artifact=task_update,
                    text=artifact_text,
                )
            else:
                yield StreamEvent(
                    event_type="task",
                    task=received_task,
                    text=extract_text_from_task(received_task),
                )

    async def set_push_config(
        self,
        task_id: str,
        webhook_url: str,
        authentication_token: str | None = None,
    ) -> TaskPushNotificationConfig:
        """Set push notification configuration for a task.

        Args:
            task_id: ID of the task
            webhook_url: Webhook URL to receive notifications
            authentication_token: Optional authentication token

        Returns:
            The created push notification configuration
        """
        validate_resource_id(task_id, "task_id")
        validate_webhook_url(webhook_url)
        if authentication_token:
            reject_control_chars(authentication_token, "authentication_token")

        client = await self._get_or_create_client()

        push_config = TaskPushNotificationConfig(
            task_id=task_id,
            push_notification_config=PushNotificationConfig(
                url=webhook_url,
                token=authentication_token,
            ),
        )
        logger.info("Setting push config for task %s: %s", task_id, webhook_url)

        return await client.set_task_callback(push_config)

    async def get_push_config(
        self,
        task_id: str,
        config_id: str | None = None,
    ) -> TaskPushNotificationConfig:
        """Get push notification configuration for a task.

        Args:
            task_id: ID of the task
            config_id: Optional specific config ID to retrieve

        Returns:
            The push notification configuration
        """
        client = await self._get_or_create_client()

        params = GetTaskPushNotificationConfigParams(
            id=task_id,
            push_notification_config_id=config_id,
        )
        logger.info("Getting push config for task %s", task_id)

        return await client.get_task_callback(params)
