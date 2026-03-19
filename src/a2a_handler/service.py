"""A2A protocol service layer.

Provides a unified interface for A2A operations, shared between the CLI and TUI.
"""

import uuid
from dataclasses import dataclass
from typing import AsyncIterator

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
class SendResult:
    """Result from sending a message to an agent.

    This is a Handler convenience wrapper around SDK types (Task, Message).
    All A2A protocol data is accessible via the `task` and `message` fields.
    """

    task: Task | None = None
    message: Message | None = None
    text: str = ""

    @property
    def context_id(self) -> str | None:
        """Get context_id from the underlying SDK type."""
        if self.task:
            return self.task.context_id
        if self.message:
            return self.message.context_id
        return None

    @property
    def task_id(self) -> str | None:
        """Get task_id from the underlying SDK type."""
        if self.task:
            return self.task.id
        if self.message:
            return self.message.task_id
        return None

    @property
    def state(self) -> TaskState | None:
        """Get task state from the underlying SDK type."""
        if self.task and self.task.status:
            return self.task.status.state
        return None

    @property
    def is_complete(self) -> bool:
        """Check if the task reached a terminal state."""
        return self.state in TERMINAL_TASK_STATES if self.state else False

    @property
    def needs_input(self) -> bool:
        """Check if the task is waiting for user input."""
        return self.state == TaskState.input_required if self.state else False

    @property
    def needs_auth(self) -> bool:
        """Check if the task requires authentication."""
        return self.state == TaskState.auth_required if self.state else False


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


@dataclass
class TaskResult:
    """Result from a task operation (get/cancel).

    This is a Handler convenience wrapper around the SDK Task type.
    All A2A protocol data is accessible via the `task` field.
    """

    task: Task
    text: str = ""

    @property
    def task_id(self) -> str:
        """Get task_id from the underlying SDK type."""
        return self.task.id

    @property
    def context_id(self) -> str:
        """Get context_id from the underlying SDK type."""
        return self.task.context_id

    @property
    def state(self) -> TaskState:
        """Get task state from the underlying SDK type."""
        return self.task.status.state if self.task.status else TaskState.unknown


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
        else:
            logger.debug(
                "Applied authentication headers: %s", list(auth_headers.keys())
            )

    def clear_credentials(self) -> None:
        """Clear authentication credentials from the service and HTTP client."""
        for header_name in self._applied_auth_headers:
            self.http_client.headers.pop(header_name, None)
        self._applied_auth_headers.clear()
        self.credentials = None
        # Rebuild the SDK client so cleared headers are guaranteed to be used.
        self._cached_client = None
        logger.debug("Cleared authentication headers")

    async def get_card(self) -> AgentCard:
        """Fetch and cache the agent card.

        Tries the standard well-known path first (``agent-card.json``), then
        falls back to the previous path (``agent.json``) used by older ADK
        versions.

        Returns:
            The agent's card with metadata and capabilities
        """
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

    async def _get_or_create_client(self) -> Client:
        """Get or create the A2A client.

        Returns:
            Configured A2A client instance
        """
        if self._cached_client is None:
            agent_card = await self.get_card()

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
    ) -> SendResult:
        """Send a message to the agent and wait for completion.

        This method collects all streaming events and returns the final result.

        Args:
            message_text: Message to send
            context_id: Optional context ID for conversation continuity
            task_id: Optional task ID to continue

        Returns:
            SendResult with task state, extracted text, and IDs
        """
        client = await self._get_or_create_client()
        user_message = self._build_user_message(message_text, context_id, task_id)

        truncated_message = (
            message_text[:50] if len(message_text) > 50 else message_text
        )
        logger.info("Sending message: %s", truncated_message)

        result = SendResult()

        async for event in client.send_message(user_message):
            if isinstance(event, Message):
                result.message = event
                result.text = extract_text_from_message_parts(event.parts)
                logger.debug("Received message response")
            elif isinstance(event, tuple):
                received_task, task_update = event
                result.task = received_task
                logger.debug(
                    "Received task update: %s",
                    received_task.status.state if received_task.status else "unknown",
                )

        if result.task:
            result.text = extract_text_from_task(result.task)

        logger.info("Send complete: task_id=%s, state=%s", result.task_id, result.state)
        return result

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
    ) -> TaskResult:
        """Get the current state of a task.

        Args:
            task_id: ID of the task to retrieve
            history_length: Optional number of history messages to include

        Returns:
            TaskResult with task state and details
        """
        client = await self._get_or_create_client()

        query_params = TaskQueryParams(id=task_id, history_length=history_length)
        logger.info("Getting task: %s", task_id)

        task = await client.get_task(query_params)

        return TaskResult(
            task=task,
            text=extract_text_from_task(task),
        )

    async def cancel_task(self, task_id: str) -> TaskResult:
        """Cancel a running task.

        Args:
            task_id: ID of the task to cancel

        Returns:
            TaskResult with updated task state
        """
        client = await self._get_or_create_client()

        task_id_params = TaskIdParams(id=task_id)
        logger.info("Canceling task: %s", task_id)

        task = await client.cancel_task(task_id_params)

        return TaskResult(
            task=task,
            text=extract_text_from_task(task),
        )

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
