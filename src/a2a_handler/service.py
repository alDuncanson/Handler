"""A2A protocol service layer.

Provides a unified interface for A2A operations, shared between the CLI and TUI.

This module is also the single place where the a2a-sdk's protobuf-based
protocol types are constructed, inspected, and serialized. The rest of Handler
(CLI, TUI, MCP) goes through the helpers defined here rather than touching
``a2a.types`` protobuf idioms (``HasField``, ``MessageToDict``, enum ints)
directly.
"""

import copy
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable, Union

import httpx
from a2a.client import Client, ClientConfig, ClientFactory

# ``parse_agent_card`` is not re-exported from ``a2a.client``, but Handler needs
# the same parse (and v0.3 compatibility shims) the SDK's resolver applies while
# keeping the served JSON, which the resolver discards.
from a2a.client.card_resolver import parse_agent_card
from a2a.client.errors import AgentCardResolutionError
from a2a.helpers import get_data_parts, get_text_parts
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
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
from google.protobuf.json_format import ParseError

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    reject_control_chars,
    validate_agent_url,
    validate_resource_id,
    validate_webhook_url,
)

logger = get_logger(__name__)

# The v1.0 SDK dropped ``PREV_AGENT_CARD_WELL_KNOWN_PATH``; keep the legacy
# path locally so Handler can still fall back to it for older servers.
LEGACY_AGENT_CARD_WELL_KNOWN_PATH = "/.well-known/agent.json"

TERMINAL_TASK_STATES = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_REJECTED,
}


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


def role_label(role: int | None) -> str:
    """Return a compact, human-readable label for a ``Role`` value."""
    if not role:
        return "unknown"
    return Role.Name(role).removeprefix("ROLE_").lower()


UNKNOWN_PROTOCOL_VERSION = "unknown"


def _raw_interface_versions(raw_card: dict[str, Any]) -> set[str]:
    """Collect per-interface protocol versions from a served card's JSON."""
    interfaces = raw_card.get("supportedInterfaces") or raw_card.get(
        "supported_interfaces"
    )
    if not isinstance(interfaces, list):
        return set()
    versions = set()
    for interface in interfaces:
        if not isinstance(interface, dict):
            continue
        version = interface.get("protocolVersion") or interface.get("protocol_version")
        if isinstance(version, str) and version:
            versions.add(version)
    return versions


def card_protocol_version(
    card: AgentCard | None,
    raw_card: dict[str, Any] | None = None,
) -> str:
    """Return the protocol version(s) a card advertises.

    A2A v1.0 puts the protocol version on each supported interface. v0.3 put a
    single ``protocolVersion`` at the top level of the card.

    The SDK parser normally migrates a v0.3 top-level ``protocolVersion`` onto
    ``supportedInterfaces``, but it skips that migration when the card already
    advertises ``supportedInterfaces`` of its own -- and the v1.0 ``AgentCard``
    has no top-level field to fall back on, so the version is dropped outright.
    Cards that advertise both shapes therefore need the served JSON to answer
    this question, which is why ``raw_card`` is consulted second.

    Returns ``UNKNOWN_PROTOCOL_VERSION`` when no version can be determined.
    """
    if card is not None:
        versions = sorted(
            {
                interface.protocol_version
                for interface in card.supported_interfaces
                if interface.protocol_version
            }
        )
        if versions:
            return ", ".join(versions)

    if raw_card:
        raw_versions = sorted(_raw_interface_versions(raw_card))
        if raw_versions:
            return ", ".join(raw_versions)
        top_level = raw_card.get("protocolVersion")
        if isinstance(top_level, str) and top_level:
            return top_level

    return UNKNOWN_PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class FetchedAgentCard:
    """An agent card as both the typed model and the JSON the server sent.

    The typed ``card`` is lossy: the v1.0 ``AgentCard`` has no field for the
    v0.3 top-level ``protocolVersion``, ``url`` or ``preferredTransport``, so
    the parser drops them. ``raw`` keeps what the server actually served, for
    display and for resolving the protocol version.
    """

    card: AgentCard
    raw: dict[str, Any]

    @property
    def protocol_version(self) -> str:
        """Return the protocol version(s) this card advertises."""
        return card_protocol_version(self.card, self.raw)


async def _fetch_card_from_path(
    http_client: httpx.AsyncClient,
    agent_url: str,
    card_path: str,
) -> FetchedAgentCard:
    """Fetch and parse an agent card from one well-known path."""
    target_url = f"{agent_url.rstrip('/')}/{card_path.lstrip('/')}"
    response = await http_client.get(target_url)
    response.raise_for_status()

    try:
        raw = response.json()
    except ValueError as error:
        raise AgentCardResolutionError(
            f"Failed to parse JSON for agent card from {target_url}: {error}"
        ) from error

    if not isinstance(raw, dict):
        raise AgentCardResolutionError(
            f"Agent card from {target_url} is not a JSON object"
        )

    try:
        # ``parse_agent_card`` mutates the dict it is handed (it pops the v0.3
        # connection fields), so give it a copy and keep ``raw`` as served.
        card = parse_agent_card(copy.deepcopy(raw))
    except ParseError as error:
        raise AgentCardResolutionError(
            f"Failed to validate agent card structure from {target_url}: {error}"
        ) from error

    return FetchedAgentCard(card=card, raw=raw)


async def fetch_agent_card(
    http_client: httpx.AsyncClient,
    agent_url: str,
) -> FetchedAgentCard:
    """Fetch an agent card, keeping the served JSON alongside the typed model.

    Tries the standard well-known path first (``agent-card.json``), then falls
    back to the previous path (``agent.json``) used by older ADK versions.
    """
    try:
        return await _fetch_card_from_path(
            http_client, agent_url, AGENT_CARD_WELL_KNOWN_PATH
        )
    except (AgentCardResolutionError, httpx.HTTPStatusError):
        logger.info(
            "Agent card not found at %s, trying %s",
            AGENT_CARD_WELL_KNOWN_PATH,
            LEGACY_AGENT_CARD_WELL_KNOWN_PATH,
        )
        return await _fetch_card_from_path(
            http_client, agent_url, LEGACY_AGENT_CARD_WELL_KNOWN_PATH
        )


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
    """Extract text from task artifacts, falling back to history if no artifacts."""
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
    state = response_state(response)
    return state in TERMINAL_TASK_STATES if state else False


def response_needs_auth(response: A2AResponse) -> bool:
    """Check if the response requires authentication."""
    return response_state(response) == TaskState.TASK_STATE_AUTH_REQUIRED


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
        self._cached_agent_card: FetchedAgentCard | None = None
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

    async def _load_agent_card(self) -> FetchedAgentCard:
        """Fetch and cache the agent card without mutating auth state."""
        if self._cached_agent_card is None:
            logger.info("Fetching agent card from %s", self.agent_url)
            self._cached_agent_card = await fetch_agent_card(
                self.http_client, self.agent_url
            )
            logger.info("Connected to agent: %s", self._cached_agent_card.card.name)
        return self._cached_agent_card

    async def get_card_document(self) -> FetchedAgentCard:
        """Fetch and cache the agent card as served JSON plus the typed model.

        Prefer this over :meth:`get_card` when the caller displays the card or
        needs its protocol version, since the typed model alone drops the v0.3
        top-level ``protocolVersion``, ``url`` and ``preferredTransport``.

        Returns:
            The served card JSON alongside the parsed ``AgentCard``
        """
        await self.ensure_oauth2_token()
        return await self._load_agent_card()

    async def get_card(self) -> AgentCard:
        """Fetch and cache the agent card.

        Tries the standard well-known path first (``agent-card.json``), then
        falls back to the previous path (``agent.json``) used by older ADK
        versions.

        Returns:
            The agent's card with metadata and capabilities
        """
        return (await self.get_card_document()).card

    async def _get_or_create_client(self) -> Client:
        """Get or create the A2A client.

        Returns:
            Configured A2A client instance
        """
        await self.ensure_oauth2_token()
        if self._cached_client is None:
            agent_card = (await self._load_agent_card()).card

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
            return bool(self._cached_agent_card.card.capabilities.streaming)
        return False

    @property
    def supports_push_notifications(self) -> bool:
        """Check if the agent supports push notifications."""
        if self._cached_agent_card:
            return bool(self._cached_agent_card.card.capabilities.push_notifications)
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
