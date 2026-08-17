"""A2A protocol service layer.

Provides a unified interface for A2A operations, shared between the CLI and TUI.

This module is also the single place where the a2a-sdk's protobuf-based
protocol types are constructed, inspected, and serialized. The rest of Handler
(CLI, TUI, MCP) goes through the helpers defined here rather than touching
``a2a.types`` protobuf idioms (``HasField``, ``MessageToDict``, enum ints)
directly.
"""

import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable, Union, cast

import httpx
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.client.errors import AgentCardResolutionError
from a2a.helpers import get_data_parts, get_text_parts
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
    Task,
    TaskArtifactUpdateEvent,
    TaskPushNotificationConfig,
    TaskState,
    TaskStatusUpdateEvent,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH, TransportProtocol
from google.protobuf import json_format

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    reject_control_chars,
    validate_agent_url,
    validate_resource_id,
    validate_webhook_url,
)

logger = get_logger(__name__)

# The v1.0 SDK dropped ``PREV_AGENT_CARD_WELL_KNOWN_PATH``; keep the legacy
# path locally so Handler can still fall back to it for older servers.
LEGACY_AGENT_CARD_WELL_KNOWN_PATH = "/.well-known/agent.json"

# Tasks fetched per ListTasks request when the caller does not choose a page
# size. Servers reject a zero (i.e. unset) page size outright.
DEFAULT_LIST_TASKS_PAGE_SIZE = 50

TERMINAL_TASK_STATES = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_REJECTED,
}

# States where the task is still open but the agent has handed control back and
# will not progress until the client acts. A client that waits for a terminal
# state without checking these will hang forever.
INTERRUPTED_TASK_STATES = {
    TaskState.TASK_STATE_INPUT_REQUIRED,
    TaskState.TASK_STATE_AUTH_REQUIRED,
}


def state_is_terminal(state: int | None) -> bool:
    """Return whether a task state means the task will never progress further."""
    return state in TERMINAL_TASK_STATES if state else False


def state_is_interrupted(state: int | None) -> bool:
    """Return whether a task is paused waiting on the client."""
    return state in INTERRUPTED_TASK_STATES if state else False


def state_needs_input(state: int | None) -> bool:
    """Return whether the agent is waiting for another message from the user."""
    return state == TaskState.TASK_STATE_INPUT_REQUIRED


def state_needs_auth(state: int | None) -> bool:
    """Return whether the agent is waiting for the client to authenticate."""
    return state == TaskState.TASK_STATE_AUTH_REQUIRED


def state_is_settled(state: int | None) -> bool:
    """Return whether a turn should stop waiting on this state.

    A turn ends either because the task finished or because the agent handed
    control back to the client.
    """
    return state_is_terminal(state) or state_is_interrupted(state)


def to_json_dict(message: Any) -> dict[str, Any]:
    """Serialize an A2A protobuf message to its canonical JSON dict.

    Uses protobuf JSON mapping (camelCase keys, enum names, unset fields
    omitted), which matches the A2A v1.0 wire format.
    """
    return json_format.MessageToDict(message)


def state_label(state: int | None) -> str:
    """Return a compact, human-readable label for a ``TaskState`` value."""
    if not state:
        return "unknown"
    return TaskState.Name(state).removeprefix("TASK_STATE_").lower()


#: Compact labels for every real task state, e.g. ``completed``,
#: ``input_required``. Used for CLI choices and label parsing.
TASK_STATE_LABELS = tuple(state_label(value) for value in TaskState.values() if value)


def task_state_from_label(label: str) -> int:
    """Return the ``TaskState`` value for a compact label like ``completed``.

    Accepts hyphens or underscores (``input-required`` and ``input_required``
    both work).
    """
    normalized = label.strip().lower().replace("-", "_")
    try:
        return TaskState.Value(f"TASK_STATE_{normalized.upper()}")
    except ValueError:
        raise InputValidationError(
            code="invalid_task_state",
            message=f"Unknown task state: {label}",
            suggestion=f"Use one of: {', '.join(TASK_STATE_LABELS)}",
            details={"field": "status"},
        ) from None


def role_label(role: int | None) -> str:
    """Return a compact, human-readable label for a ``Role`` value."""
    if not role:
        return "unknown"
    return Role.Name(role).removeprefix("ROLE_").lower()


def card_protocol_version(card: AgentCard) -> str:
    """Return the protocol version(s) advertised by a card's interfaces.

    In A2A v1.0 the protocol version lives on each supported interface rather
    than at the top level of the card.
    """
    versions = sorted(
        {
            interface.protocol_version
            for interface in card.supported_interfaces
            if interface.protocol_version
        }
    )
    return ", ".join(versions) if versions else "unknown"


def part_kind(part: Part) -> str:
    """Return a compact display label for an A2A part."""
    if part.HasField("text"):
        return "text"
    if part.HasField("data"):
        return "data"
    if part.HasField("url") or part.HasField("raw"):
        return "file"
    return "unknown"


def part_text(part: Part) -> str:
    """Return the text of a part, or an empty string if it is not a text part."""
    return part.text if part.HasField("text") else ""


def part_data(part: Part) -> Any:
    """Return the decoded Python value carried by a data part."""
    decoded = get_data_parts([part])
    return decoded[0] if decoded else {}


def part_file(part: Part) -> dict[str, Any]:
    """Return a description of a file part (name, media type, uri, byte count)."""
    info: dict[str, Any] = {}
    if part.filename:
        info["name"] = part.filename
    if part.media_type:
        info["media_type"] = part.media_type
    if part.HasField("url"):
        info["uri"] = part.url
    if part.HasField("raw"):
        info["num_bytes"] = len(part.raw)
    return info


@dataclass
class StreamEvent:
    """A single event from a streaming response.

    This is a Handler convenience wrapper around SDK streaming event types.
    The original SDK event is accessible via `status` or `artifact` fields.

    ``task`` carries Handler's running aggregate of the task (rebuilt from
    status/artifact updates), so consumers always see the latest known state.
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
            return self.task.context_id or None
        if self.message:
            return self.message.context_id or None
        if self.status:
            return self.status.context_id or None
        if self.artifact:
            return self.artifact.context_id or None
        return None

    @property
    def task_id(self) -> str | None:
        """Get task_id from the underlying SDK type."""
        if self.task:
            return self.task.id or None
        if self.message:
            return self.message.task_id or None
        if self.status:
            return self.status.task_id or None
        if self.artifact:
            return self.artifact.task_id or None
        return None

    @property
    def state(self) -> int | None:
        """Get task state from the underlying SDK type."""
        if self.task:
            return self.task.status.state or None
        if self.status:
            return self.status.status.state or None
        return None


def extract_text_from_message_parts(message_parts: Iterable[Part] | None) -> str:
    """Extract text content from message parts."""
    if not message_parts:
        return ""
    return "\n".join(text for text in get_text_parts(list(message_parts)) if text)


def extract_text_from_task(task: Task) -> str:
    """Extract an agent's text from a task.

    Prefers artifacts, then agent messages in history, then the status message.
    The last of those matters for a task that pauses rather than finishes: an
    agent asking a question often carries it only on the status, and without
    this fallback the user is shown a paused task with nothing to read.
    """
    extracted_texts = []

    if task.artifacts:
        for artifact in task.artifacts:
            if artifact.parts:
                extracted_texts.append(extract_text_from_message_parts(artifact.parts))

    # Only check history if no artifacts found (avoids duplication)
    if not extracted_texts and task.history:
        for message in task.history:
            if message.role == Role.ROLE_AGENT and message.parts:
                extracted_texts.append(extract_text_from_message_parts(message.parts))

    if not any(extracted_texts) and task.status.HasField("message"):
        extracted_texts.append(
            extract_text_from_message_parts(task.status.message.parts)
        )

    return "\n".join(text for text in extracted_texts if text)


A2AResponse = Union[Task, Message]


def response_context_id(response: A2AResponse) -> str | None:
    """Get context_id from a Task or Message."""
    return response.context_id or None


def response_task_id(response: A2AResponse) -> str | None:
    """Get task_id from a Task or Message."""
    if isinstance(response, Task):
        return response.id or None
    return response.task_id or None


def response_state(response: A2AResponse) -> int | None:
    """Get task state from a Task or Message (Messages have no state)."""
    if isinstance(response, Task):
        return response.status.state or None
    return None


def is_terminal(response: A2AResponse) -> bool:
    """Check if the response reached a terminal state."""
    return state_is_terminal(response_state(response))


def response_needs_auth(response: A2AResponse) -> bool:
    """Check if the response requires authentication."""
    return state_needs_auth(response_state(response))


def response_needs_input(response: A2AResponse) -> bool:
    """Check if the agent is waiting for another message from the user."""
    return state_needs_input(response_state(response))


def continuation_task_id(response: A2AResponse) -> str | None:
    """Return the task ID a follow-up message should continue, if any.

    A terminal task cannot accept more messages, so it yields ``None``. An
    interrupted task (input or auth required) is still open and must be
    continued by ID, otherwise the agent loses the thread.
    """
    if is_terminal(response):
        return None
    return response_task_id(response)


def extract_text(response: A2AResponse) -> str:
    """Extract text content from a Task or Message."""
    if isinstance(response, Task):
        return extract_text_from_task(response)
    return extract_text_from_message_parts(response.parts)


def protocol_dump(response: A2AResponse) -> dict[str, object]:
    """Serialize an A2A protocol object to a JSON-compatible dict."""
    return to_json_dict(response)


def _truncate_secret(value: str) -> str:
    """Return a short preview for secrets without exposing the full value."""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def push_config_dump(config: TaskPushNotificationConfig) -> dict[str, object]:
    """Serialize push-config data while redacting webhook auth tokens."""
    data = to_json_dict(config)
    token = data.get("token")
    if not isinstance(token, str) or not token:
        return data

    redacted = dict(data)
    redacted["token"] = _truncate_secret(token)
    return redacted


def _apply_status_update(
    current_task: Task | None, update: TaskStatusUpdateEvent
) -> Task:
    """Fold a status update into the running task aggregate."""
    if current_task is None:
        current_task = Task(id=update.task_id, context_id=update.context_id)
    current_task.status.CopyFrom(update.status)
    return current_task


def _apply_artifact_update(
    current_task: Task | None, update: TaskArtifactUpdateEvent
) -> Task:
    """Fold an artifact update into the running task aggregate."""
    if current_task is None:
        current_task = Task(id=update.task_id, context_id=update.context_id)
    artifact = update.artifact
    for existing in current_task.artifacts:
        if existing.artifact_id and existing.artifact_id == artifact.artifact_id:
            if update.append:
                existing.parts.extend(artifact.parts)
            else:
                existing.CopyFrom(artifact)
            break
    else:
        current_task.artifacts.append(artifact)
    return current_task


async def _translate_stream(
    chunks: AsyncIterator[StreamResponse],
) -> AsyncIterator[StreamEvent]:
    """Translate raw SDK ``StreamResponse`` chunks into Handler ``StreamEvent``s.

    Maintains a running task aggregate so every emitted event exposes the
    latest known task snapshot via ``StreamEvent.task``.
    """
    current_task: Task | None = None

    async for chunk in chunks:
        if chunk.HasField("message"):
            yield StreamEvent(
                event_type="message",
                message=chunk.message,
                text=extract_text_from_message_parts(chunk.message.parts),
            )
        elif chunk.HasField("task"):
            current_task = chunk.task
            yield StreamEvent(
                event_type="task",
                task=current_task,
                text=extract_text_from_task(current_task),
            )
        elif chunk.HasField("status_update"):
            update = chunk.status_update
            current_task = _apply_status_update(current_task, update)
            status_text = ""
            if update.status.HasField("message"):
                status_text = extract_text_from_message_parts(
                    update.status.message.parts
                )
            yield StreamEvent(
                event_type="status",
                task=current_task,
                status=update,
                text=status_text,
            )
        elif chunk.HasField("artifact_update"):
            update = chunk.artifact_update
            current_task = _apply_artifact_update(current_task, update)
            artifact_text = ""
            if update.artifact.parts:
                artifact_text = extract_text_from_message_parts(update.artifact.parts)
            yield StreamEvent(
                event_type="artifact",
                task=current_task,
                artifact=update,
                text=artifact_text,
            )


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
            except (AgentCardResolutionError, httpx.HTTPStatusError):
                logger.info(
                    "Agent card not found at %s, trying %s",
                    AGENT_CARD_WELL_KNOWN_PATH,
                    LEGACY_AGENT_CARD_WELL_KNOWN_PATH,
                )
                fallback_resolver = A2ACardResolver(
                    self.http_client,
                    self.agent_url,
                    agent_card_path=LEGACY_AGENT_CARD_WELL_KNOWN_PATH,
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

            push_notification_config: TaskPushNotificationConfig | None = None
            if self.push_notification_url:
                push_notification_config = TaskPushNotificationConfig(
                    url=self.push_notification_url,
                    token=self.push_notification_token or "",
                )
                logger.info(
                    "Push notification configured: %s", self.push_notification_url
                )

            client_config = ClientConfig(
                httpx_client=self.http_client,
                supported_protocol_bindings=[TransportProtocol.JSONRPC.value],
                streaming=self.enable_streaming,
                push_notification_config=push_notification_config,
            )

            client_factory = ClientFactory(client_config)
            self._cached_client = client_factory.create(agent_card)
            logger.debug("Created A2A client for %s", agent_card.name)

        return self._cached_client

    @property
    def supports_streaming(self) -> bool:
        """Check if the agent supports streaming."""
        if self._cached_agent_card:
            return bool(self._cached_agent_card.capabilities.streaming)
        return False

    @property
    def supports_push_notifications(self) -> bool:
        """Check if the agent supports push notifications."""
        if self._cached_agent_card:
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
            message_id=uuid.uuid4().hex,
            role=Role.ROLE_USER,
            parts=[Part(text=message_text)],
            context_id=context_id or "",
            task_id=task_id or "",
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

        request = SendMessageRequest(message=user_message)

        last_task: Task | None = None
        last_message: Message | None = None

        async for event in _translate_stream(client.send_message(request)):
            if event.task is not None:
                last_task = event.task
            elif event.message is not None:
                last_message = event.message

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

        request = SendMessageRequest(message=user_message)

        async for event in _translate_stream(client.send_message(request)):
            yield event

    async def get_task(
        self,
        task_id: str,
        history_length: int | None = None,
    ) -> Task:
        """Get the current state of a task.

        Returns the raw A2A Task object.
        """
        client = await self._get_or_create_client()

        request = GetTaskRequest(id=task_id)
        if history_length is not None:
            request.history_length = history_length
        logger.info("Getting task: %s", task_id)

        return await client.get_task(request)

    async def cancel_task(self, task_id: str) -> Task:
        """Cancel a running task.

        Returns the raw A2A Task object with updated state.
        """
        client = await self._get_or_create_client()

        logger.info("Canceling task: %s", task_id)

        return await client.cancel_task(CancelTaskRequest(id=task_id))

    async def list_tasks(
        self,
        context_id: str | None = None,
        status: int | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
        history_length: int | None = None,
        include_artifacts: bool = False,
    ) -> ListTasksResponse:
        """List tasks on the agent, one page at a time.

        Args:
            context_id: Only return tasks in this context
            status: Only return tasks in this ``TaskState``
            page_size: Maximum tasks per page (server may return fewer);
                defaults to ``DEFAULT_LIST_TASKS_PAGE_SIZE``
            page_token: Continuation token from a previous page's
                ``next_page_token``
            history_length: Number of history messages to include per task
            include_artifacts: Whether to include task artifacts

        Returns:
            The raw ``ListTasksResponse`` with tasks and the next page token.
        """
        if context_id:
            validate_resource_id(context_id, "context_id")
        if page_token:
            reject_control_chars(page_token, "page_token")

        client = await self._get_or_create_client()

        # An unset proto3 int is indistinguishable from 0, and servers reject a
        # zero page size, so always send an explicit one.
        request = ListTasksRequest(
            context_id=context_id or "",
            page_size=page_size or DEFAULT_LIST_TASKS_PAGE_SIZE,
            page_token=page_token or "",
            include_artifacts=include_artifacts,
        )
        if status is not None:
            request.status = cast("TaskState", status)
        if history_length is not None:
            request.history_length = history_length

        logger.info(
            "Listing tasks (context_id=%s, status=%s, page_token=%s)",
            context_id,
            state_label(status) if status else "any",
            page_token or "",
        )

        return await client.list_tasks(request)

    async def list_all_tasks(
        self,
        context_id: str | None = None,
        status: int | None = None,
        page_size: int | None = None,
        history_length: int | None = None,
        include_artifacts: bool = False,
    ) -> list[Task]:
        """List tasks across every page, following continuation tokens.

        A repeated token stops the loop, so a server that keeps returning the
        same page cannot spin this forever.
        """
        tasks: list[Task] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()

        while True:
            response = await self.list_tasks(
                context_id=context_id,
                status=status,
                page_size=page_size,
                page_token=page_token,
                history_length=history_length,
                include_artifacts=include_artifacts,
            )
            tasks.extend(response.tasks)
            page_token = response.next_page_token
            if not page_token or page_token in seen_tokens:
                break
            seen_tokens.add(page_token)

        logger.info(
            "Listed %d task(s) across %d page(s)", len(tasks), len(seen_tokens) + 1
        )
        return tasks

    async def resubscribe(self, task_id: str) -> AsyncIterator[StreamEvent]:
        """Resubscribe to a task's event stream.

        Args:
            task_id: ID of the task to resubscribe to

        Yields:
            StreamEvent objects as they are received
        """
        client = await self._get_or_create_client()

        logger.info("Resubscribing to task: %s", task_id)

        subscription = client.subscribe(SubscribeToTaskRequest(id=task_id))
        async for event in _translate_stream(subscription):
            yield event

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
            url=webhook_url,
            token=authentication_token or "",
        )
        logger.info("Setting push config for task %s: %s", task_id, webhook_url)

        return await client.create_task_push_notification_config(push_config)

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

        request = GetTaskPushNotificationConfigRequest(
            task_id=task_id,
            id=config_id or "",
        )
        logger.info("Getting push config for task %s", task_id)

        return await client.get_task_push_notification_config(request)
