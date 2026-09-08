"""A2A protocol service layer.

Provides a unified interface for A2A operations, shared between the CLI and TUI.

This module is also the single place where the a2a-sdk's protobuf-based
protocol types are constructed, inspected, and serialized. The rest of Handler
(CLI, TUI, MCP) goes through the helpers defined here rather than touching
``a2a.types`` protobuf idioms (``HasField``, ``MessageToDict``, enum ints)
directly.
"""

import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Sequence, Union, cast
from urllib.parse import urlparse

import httpx
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError, AgentCardResolutionError
from a2a.helpers import (
    get_data_parts,
    get_text_parts,
    new_data_part,
    new_raw_part,
    new_url_part,
)
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTaskPushNotificationConfigsResponse,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
    Task,
    TaskArtifactUpdateEvent,
    TaskPushNotificationConfig,
    TaskState,
    TaskStatusUpdateEvent,
)
from a2a.extensions.common import HTTP_EXTENSION_HEADER
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH, TransportProtocol
from a2a.utils.errors import ExtendedAgentCardNotConfiguredError
from google.protobuf import json_format

from a2a_handler.auth import (
    TOKEN_FETCHING_AUTH_TYPES,
    AuthCredentials,
    AuthType,
)
from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    reject_control_chars,
    validate_agent_url,
    validate_history_length,
    validate_page_size,
    validate_resource_id,
    validate_webhook_url,
)

logger = get_logger(__name__)

# The v1.0 SDK dropped ``PREV_AGENT_CARD_WELL_KNOWN_PATH``; keep the legacy
# path locally so Handler can still fall back to it for older servers.
LEGACY_AGENT_CARD_WELL_KNOWN_PATH = "/.well-known/agent.json"

# Hard bound on pagination so a server minting a fresh continuation token on
# every response cannot spin list_all_tasks forever.
MAX_LIST_TASKS_PAGES = 1000


@dataclass(frozen=True, slots=True)
class TaskListing:
    """Every task a full listing produced, plus whether it was cut short.

    ``truncated`` is True when a pagination defense (page cap or a
    non-progressing server) stopped the crawl before the server ran out of
    continuation tokens; the tasks list is then incomplete.
    """

    tasks: list[Task]
    truncated: bool = False


# Configs fetched per ListTaskPushNotificationConfigs request when the caller
# does not choose a page size. Unlike ListTasksRequest.page_size, this field
# has no explicit presence, so an omitted value is indistinguishable on the
# wire from a literal zero. Sending a real default avoids depending on how a
# given server reads that zero.
DEFAULT_PUSH_CONFIG_PAGE_SIZE = 50


class PushConfigNotFoundError(A2AClientError):
    """Raised when a push config does not exist on the task.

    Used when get has nothing to return, and when delete would otherwise look
    successful: servers commonly treat deletes as idempotent, so Handler
    checks first. A mistyped config ID should fail loudly, not read as a
    successful removal.
    """


class PushConfigAmbiguousError(A2AClientError):
    """Raised when a task has several push configs and none was chosen.

    ``get_push_config`` without a config ID can only auto-select when the
    task has exactly one config. Several configs need an explicit ID so
    Handler never sends an empty string that servers reject as invalid.
    """


class ExtendedCardNotSupportedError(A2AClientError):
    """Raised when an extended agent card is requested but not on offer.

    Covers both the agent whose public card never advertised one and the
    server that advertises support yet has no extended card configured, so
    callers get one clear message instead of a raw protocol error.
    """


GRPC_INSTALL_HINT = (
    "Install Handler's gRPC extra to talk to this agent: "
    "pip install 'a2a-handler[grpc]' (or uv tool install 'a2a-handler[grpc]')"
)


class TransportNegotiationError(A2AClientError):
    """Raised when no transport both sides support could be agreed on."""


def grpc_transport_available() -> bool:
    """Return whether the optional gRPC dependencies are installed."""
    try:
        import grpc  # noqa: F401, PLC0415  # ty: ignore[unresolved-import]

        return True
    except ImportError:
        return False


def supported_transport_bindings() -> list[str]:
    """Return the protocol bindings this Handler install can speak.

    Ordered by client preference; gRPC joins the list only when the optional
    dependencies are installed.
    """
    bindings = [
        TransportProtocol.JSONRPC.value,
        TransportProtocol.HTTP_JSON.value,
    ]
    if grpc_transport_available():
        bindings.append(TransportProtocol.GRPC.value)
    return bindings


def negotiate_transport_binding(
    card: AgentCard,
    client_bindings: Iterable[str],
) -> str | None:
    """Return the binding the SDK will pick for this card, or None.

    Mirrors the SDK's server-preference negotiation: the first interface the
    card advertises whose binding the client also speaks wins.
    """
    client_set = set(client_bindings)
    for interface in card.supported_interfaces:
        if interface.protocol_binding in client_set:
            return interface.protocol_binding
    return None


def _grpc_channel_factory(url: str) -> Any:
    """Create a gRPC channel for an agent interface URL."""
    # Only reachable when the optional grpc extra is installed.
    import grpc  # noqa: PLC0415  # ty: ignore[unresolved-import]

    parsed = urlparse(url)
    target = parsed.netloc or url
    if parsed.scheme == "https":
        return grpc.aio.secure_channel(target, grpc.ssl_channel_credentials())
    return grpc.aio.insecure_channel(target)


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
    both work). Only the real states in ``TASK_STATE_LABELS`` are accepted:
    ``unspecified`` maps to the proto default and would silently drop a
    filter, so it is rejected like any unknown label.
    """
    normalized = label.strip().lower().replace("-", "_")
    if normalized not in TASK_STATE_LABELS:
        raise InputValidationError(
            code="invalid_task_state",
            message=f"Unknown task state: {label}",
            suggestion=f"Use one of: {', '.join(TASK_STATE_LABELS)}",
            details={"field": "status"},
        )
    return TaskState.Value(f"TASK_STATE_{normalized.upper()}")


def role_label(role: int | None) -> str:
    """Return a compact, human-readable label for a ``Role`` value."""
    if not role:
        return "unknown"
    return Role.Name(role).removeprefix("ROLE_").lower()


def card_extensions(card: AgentCard) -> list[dict[str, Any]]:
    """Return the extensions a card declares, in A2A wire format."""
    return [to_json_dict(extension) for extension in card.capabilities.extensions]


def required_extension_uris(card: AgentCard) -> list[str]:
    """Return the URIs of extensions the card marks as required."""
    return [
        extension.uri
        for extension in card.capabilities.extensions
        if extension.required and extension.uri
    ]


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


# Inline file bytes travel base64-encoded inside the request body, so the wire
# payload is ~4/3 the file size. Servers commonly reject bodies much past this;
# larger files should be sent by reference as a ``url`` part instead.
MAX_INLINE_FILE_BYTES = 10 * 1024 * 1024

_DEFAULT_MEDIA_TYPE = "application/octet-stream"


def build_data_part(value: Any) -> Part:
    """Build a structured-data part from a JSON-compatible Python value."""
    return new_data_part(value)


def build_url_part(url: str, media_type: str | None = None) -> Part:
    """Build a file-by-reference part pointing at an http(s) URL."""
    filename = Path(urlparse(url).path).name or None
    if media_type is None and filename:
        media_type = mimetypes.guess_type(filename)[0]
    return new_url_part(url, media_type=media_type, filename=filename)


def _unreadable_file_error(path: Path, reason: str) -> InputValidationError:
    return InputValidationError(
        code="unreadable_file",
        message=f"Cannot read file: {path}",
        suggestion="Check that the path exists and is a readable regular file",
        details={"field": "file", "error": reason},
    )


def _file_too_large_error(path: Path, num_bytes: int) -> InputValidationError:
    return InputValidationError(
        code="file_too_large",
        message=(
            f"{path.name} is {num_bytes} bytes, over the "
            f"{MAX_INLINE_FILE_BYTES}-byte inline limit"
        ),
        suggestion=(
            "Host the file somewhere the agent can reach and pass its "
            "http(s) URL to send it by reference"
        ),
        details={"field": "file", "num_bytes": num_bytes},
    )


def build_file_part(path: str | Path) -> Part:
    """Build an inline file part from a local path.

    The file's media type is sniffed from its name. Files over
    ``MAX_INLINE_FILE_BYTES`` are refused: they should be uploaded somewhere
    reachable and sent by URL instead. Only regular files are accepted, and
    the size is checked before reading so a huge file is rejected without
    loading it.
    """
    try:
        file_path = Path(path).expanduser()
    except RuntimeError as exc:
        # An unresolvable ~user raises RuntimeError, not OSError.
        raise _unreadable_file_error(Path(path), str(exc)) from exc
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise _unreadable_file_error(file_path, str(exc)) from exc
    if not file_path.is_file():
        raise _unreadable_file_error(file_path, "not a regular file")
    if size > MAX_INLINE_FILE_BYTES:
        raise _file_too_large_error(file_path, size)
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise _unreadable_file_error(file_path, str(exc)) from exc
    # The file can grow between the stat and the read.
    if len(raw) > MAX_INLINE_FILE_BYTES:
        raise _file_too_large_error(file_path, len(raw))
    media_type = mimetypes.guess_type(file_path.name)[0] or _DEFAULT_MEDIA_TYPE
    return new_raw_part(raw, media_type=media_type, filename=file_path.name)


def attachment_part_from_spec(spec: str) -> Part:
    """Build a file part from a local path or an http(s) URL.

    A spec that parses as an http(s) URL becomes a file-by-reference part;
    anything else is treated as a local path and inlined.
    """
    reject_control_chars(spec, "file")
    parsed = urlparse(spec)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return build_url_part(spec)
    return build_file_part(spec)


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
        extensions: Iterable[str] | None = None,
    ) -> None:
        """Initialize the A2A service.

        Args:
            http_client: Async HTTP client to use for requests
            agent_url: Base URL of the A2A agent
            enable_streaming: Whether to prefer streaming when available
            push_notification_url: Optional webhook URL for push notifications
            push_notification_token: Optional token for push notification auth
            credentials: Optional authentication credentials
            extensions: Optional A2A extension URIs to request on every call
                (sent as the ``A2A-Extensions`` header)
        """
        validate_agent_url(agent_url)
        if push_notification_url:
            validate_webhook_url(push_notification_url)
        if push_notification_token:
            reject_control_chars(push_notification_token, "push_notification_token")

        requested_extensions: list[str] = []
        for extension_uri in extensions or ():
            reject_control_chars(extension_uri, "extension")
            stripped = extension_uri.strip()
            if stripped:
                requested_extensions.append(stripped)

        self.http_client = http_client
        self.agent_url = agent_url
        self.enable_streaming = enable_streaming
        self.push_notification_url = push_notification_url
        self.push_notification_token = push_notification_token
        self.credentials = credentials
        self.extensions: tuple[str, ...] = tuple(requested_extensions)
        self._cached_client: Client | None = None
        self._cached_agent_card: AgentCard | None = None
        self._applied_auth_headers: set[str] = set()

        if self.extensions:
            self.http_client.headers[HTTP_EXTENSION_HEADER] = ", ".join(self.extensions)
            logger.info("Requesting A2A extensions: %s", ", ".join(self.extensions))

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
        elif credentials.auth_type in TOKEN_FETCHING_AUTH_TYPES:
            logger.debug(
                "%s credentials set (token will be fetched on first request)",
                credentials.auth_type.value,
            )
        else:
            logger.debug(
                "Applied authentication headers: %s", list(auth_headers.keys())
            )

    async def ensure_oauth2_token(self) -> None:
        """Fetch or refresh the OAuth2/OIDC access token if needed.

        Acquires a new token when no token is present or when the cached
        token has expired (or is about to expire within a safety margin).
        """
        if (
            self.credentials is None
            or self.credentials.auth_type not in TOKEN_FETCHING_AUTH_TYPES
        ):
            return
        if not self.credentials.is_token_expired():
            return
        if self.credentials.value:
            logger.info("Access token expired, refreshing")
            self.credentials.clear_token()
        else:
            logger.info(
                "Fetching access token from %s",
                self.credentials.token_url or self.credentials.issuer_url,
            )
        await self.credentials.fetch_oauth2_token()
        auth_headers = self.credentials.to_headers()
        self.http_client.headers.update(auth_headers)
        self._applied_auth_headers = set(auth_headers.keys())
        self._cached_client = None
        logger.info("Access token applied")

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
            missing = self.unrequested_required_extensions(self._cached_agent_card)
            if missing:
                logger.warning(
                    "Agent %s requires extension(s) this client did not request: %s",
                    self._cached_agent_card.name,
                    ", ".join(missing),
                )
        return self._cached_agent_card

    def unrequested_required_extensions(self, card: AgentCard) -> list[str]:
        """Return required extension URIs the client is not requesting.

        An agent that marks an extension required may refuse or degrade
        requests without it, so this is worth surfacing to the user.
        """
        return [
            uri for uri in required_extension_uris(card) if uri not in self.extensions
        ]

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

    @property
    def supports_extended_card(self) -> bool:
        """Whether the fetched public card advertises an extended card."""
        if self._cached_agent_card:
            return bool(self._cached_agent_card.capabilities.extended_agent_card)
        return False

    async def get_extended_card(self) -> AgentCard:
        """Fetch the extended agent card offered to authenticated clients.

        Returns:
            The extended card, which may reveal skills or interfaces the
            public card omits.

        Raises:
            ExtendedCardNotSupportedError: If the agent's public card does not
                advertise ``extended_agent_card``, or the server has no
                extended card configured despite advertising one.
        """
        card = await self.get_card()
        if not card.capabilities.extended_agent_card:
            raise ExtendedCardNotSupportedError(
                f"{card.name or self.agent_url} does not offer an extended "
                "agent card (capabilities.extendedAgentCard is not set)"
            )

        client = await self._get_or_create_client()
        logger.info("Fetching extended agent card from %s", self.agent_url)
        try:
            return await client.get_extended_agent_card(GetExtendedAgentCardRequest())
        except ExtendedAgentCardNotConfiguredError as exc:
            # The card advertised support but the server has nothing to serve.
            raise ExtendedCardNotSupportedError(
                f"{card.name or self.agent_url} advertises an extended agent "
                "card but the server has none configured"
            ) from exc

    async def _get_or_create_client(self) -> Client:
        """Get or create the A2A client.

        Returns:
            Configured A2A client instance
        """
        await self.ensure_oauth2_token()
        if self._cached_client is None:
            agent_card = await self._load_agent_card()

            # Push config is attached per message via SendMessageConfiguration
            # (where the protocol carries it), not through ClientConfig.
            bindings = supported_transport_bindings()
            client_config = ClientConfig(
                httpx_client=self.http_client,
                supported_protocol_bindings=bindings,
                grpc_channel_factory=(
                    _grpc_channel_factory if grpc_transport_available() else None
                ),
                streaming=self.enable_streaming,
            )

            client_factory = ClientFactory(client_config)
            try:
                self._cached_client = client_factory.create(agent_card)
            except ValueError as exc:
                raise self._transport_negotiation_error(agent_card, bindings) from exc
            logger.info(
                "Negotiated transport %s for %s",
                self.negotiated_transport,
                agent_card.name,
            )

        return self._cached_client

    @staticmethod
    def _transport_negotiation_error(
        agent_card: AgentCard,
        client_bindings: list[str],
    ) -> TransportNegotiationError:
        """Explain a failed negotiation instead of a bare 'no transports'."""
        offered = sorted(
            {
                interface.protocol_binding
                for interface in agent_card.supported_interfaces
                if interface.protocol_binding
            }
        )
        message = (
            f"No transport in common with {agent_card.name or 'the agent'}: "
            f"it offers {', '.join(offered) or 'none'}; this Handler install "
            f"speaks {', '.join(client_bindings)}."
        )
        if TransportProtocol.GRPC.value in offered and not grpc_transport_available():
            message = f"{message} {GRPC_INSTALL_HINT}"
        return TransportNegotiationError(message)

    @property
    def negotiated_transport(self) -> str | None:
        """The protocol binding the SDK picks for this agent, once known.

        Available as soon as the agent card has been fetched; None before.
        """
        if self._cached_agent_card is None:
            return None
        return negotiate_transport_binding(
            self._cached_agent_card, supported_transport_bindings()
        )

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
        attachments: Sequence[Part] | None = None,
    ) -> Message:
        """Build a user message.

        Args:
            message_text: Message content (may be empty when attachments carry
                the payload)
            context_id: Optional context ID for conversation continuity
            task_id: Optional task ID to continue
            attachments: Optional file or data parts to send with the text

        Returns:
            Properly formatted Message object
        """
        parts: list[Part] = []
        if message_text:
            parts.append(Part(text=message_text))
        if attachments:
            parts.extend(attachments)
        if not parts:
            raise ValueError("A message needs text or at least one attachment")
        return Message(
            message_id=uuid.uuid4().hex,
            role=Role.ROLE_USER,
            parts=parts,
            context_id=context_id or "",
            task_id=task_id or "",
        )

    def _build_send_configuration(
        self,
        accepted_output_modes: Sequence[str] | None,
        history_length: int | None,
        return_immediately: bool,
    ) -> SendMessageConfiguration | None:
        """Build the per-message configuration, or None when nothing is set.

        The service's push notification settings ride along here on every
        message; ``SendMessageConfiguration`` is where the protocol carries
        them.
        """
        push_config: TaskPushNotificationConfig | None = None
        if self.push_notification_url:
            push_config = TaskPushNotificationConfig(
                url=self.push_notification_url,
                token=self.push_notification_token or "",
            )

        if not (
            accepted_output_modes
            or history_length is not None
            or return_immediately
            or push_config is not None
        ):
            return None

        configuration = SendMessageConfiguration(
            return_immediately=return_immediately,
        )
        if accepted_output_modes:
            configuration.accepted_output_modes.extend(accepted_output_modes)
        if history_length is not None:
            configuration.history_length = history_length
        if push_config is not None:
            configuration.task_push_notification_config.CopyFrom(push_config)
        return configuration

    def _build_send_request(
        self,
        message_text: str,
        context_id: str | None,
        task_id: str | None,
        accepted_output_modes: Sequence[str] | None,
        history_length: int | None,
        return_immediately: bool,
        attachments: Sequence[Part] | None = None,
    ) -> SendMessageRequest:
        """Build a send request with its message and optional configuration."""
        user_message = self._build_user_message(
            message_text, context_id, task_id, attachments
        )
        request = SendMessageRequest(message=user_message)
        configuration = self._build_send_configuration(
            accepted_output_modes, history_length, return_immediately
        )
        if configuration is not None:
            request.configuration.CopyFrom(configuration)
        return request

    async def send(
        self,
        message_text: str,
        context_id: str | None = None,
        task_id: str | None = None,
        attachments: Sequence[Part] | None = None,
        *,
        accepted_output_modes: Sequence[str] | None = None,
        history_length: int | None = None,
        return_immediately: bool = False,
    ) -> Task | Message:
        """Send a message to the agent and wait for completion.

        Args:
            message_text: Message content
            context_id: Optional context ID for conversation continuity
            task_id: Optional task ID to continue
            accepted_output_modes: Media types the client can render
            history_length: History messages the agent should return per task
            return_immediately: Ask the agent to acknowledge with a task
                right away instead of blocking until completion

        Returns the raw A2A protocol response (Task or Message).
        """
        client = await self._get_or_create_client()

        truncated_message = (
            message_text[:50] if len(message_text) > 50 else message_text
        )
        logger.info("Sending message: %s", truncated_message)

        request = self._build_send_request(
            message_text,
            context_id,
            task_id,
            accepted_output_modes,
            history_length,
            return_immediately,
        )

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
        attachments: Sequence[Part] | None = None,
        *,
        accepted_output_modes: Sequence[str] | None = None,
        history_length: int | None = None,
        return_immediately: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Send a message and stream responses as they arrive.

        Args:
            message_text: Message to send
            context_id: Optional context ID for conversation continuity
            task_id: Optional task ID to continue
            attachments: Optional file or data parts to send with the text
            accepted_output_modes: Media types the client can render
            history_length: History messages the agent should return per task
            return_immediately: Ask the agent to acknowledge with a task
                right away instead of blocking until completion

        Yields:
            StreamEvent objects as they are received
        """
        client = await self._get_or_create_client()

        truncated_message = (
            message_text[:50] if len(message_text) > 50 else message_text
        )
        logger.info("Streaming message: %s", truncated_message)

        request = self._build_send_request(
            message_text,
            context_id,
            task_id,
            accepted_output_modes,
            history_length,
            return_immediately,
        )

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
        validate_history_length(history_length)

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
                left unset the server chooses its own default
            page_token: Continuation token from a previous page's
                ``next_page_token``. Opaque server data; it is sent back
                verbatim, not validated as user input.
            history_length: Number of history messages to include per task
            include_artifacts: Whether to include task artifacts

        Returns:
            The raw ``ListTasksResponse`` with tasks and the next page token.
        """
        if context_id:
            validate_resource_id(context_id, "context_id")
        validate_page_size(page_size)
        validate_history_length(history_length)

        client = await self._get_or_create_client()

        # page_size and history_length carry explicit presence, so they are
        # only set when the caller chose a value; unset means the server's
        # default applies.
        request = ListTasksRequest(
            context_id=context_id or "",
            page_token=page_token or "",
            include_artifacts=include_artifacts,
        )
        if page_size is not None:
            request.page_size = page_size
        if status is not None:
            request.status = cast("TaskState", status)
        if history_length is not None:
            request.history_length = history_length

        logger.info(
            "Listing tasks (context_id=%s, status=%s, page_token=%s)",
            context_id,
            state_label(status) if status is not None else "any",
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
    ) -> TaskListing:
        """List tasks across every page, following continuation tokens.

        Defenses against misbehaving servers: tasks are deduplicated by ID,
        the loop stops as soon as a page contributes nothing new while still
        offering a continuation token (which subsumes replayed pages and
        token cycles of any length), and pagination is capped at
        ``MAX_LIST_TASKS_PAGES`` so a server minting fresh tokens forever
        cannot spin the client. A listing cut short by either defense is
        marked ``truncated`` so consumers are not handed silently
        incomplete data.
        """
        tasks: list[Task] = []
        seen_task_ids: set[str] = set()
        page_token: str | None = None
        pages_fetched = 0
        truncated = False

        while True:
            response = await self.list_tasks(
                context_id=context_id,
                status=status,
                page_size=page_size,
                page_token=page_token,
                history_length=history_length,
                include_artifacts=include_artifacts,
            )
            pages_fetched += 1
            new_tasks = 0
            for task in response.tasks:
                if task.id and task.id in seen_task_ids:
                    continue
                if task.id:
                    seen_task_ids.add(task.id)
                tasks.append(task)
                new_tasks += 1

            next_token = response.next_page_token
            if not next_token:
                break
            if response.tasks and new_tasks == 0:
                logger.warning(
                    "Server offered page token %r but the page held nothing "
                    "new; stopping pagination",
                    next_token,
                )
                truncated = True
                break
            if next_token == (page_token or ""):
                logger.warning(
                    "Server repeated page token %r; stopping pagination",
                    next_token,
                )
                truncated = True
                break
            if pages_fetched >= MAX_LIST_TASKS_PAGES:
                logger.warning(
                    "Stopping after %d pages; the task listing is incomplete",
                    pages_fetched,
                )
                truncated = True
                break
            page_token = next_token

        logger.info("Listed %d task(s) across %d page(s)", len(tasks), pages_fetched)
        return TaskListing(tasks=tasks, truncated=truncated)

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

        An omitted ``config_id`` is not sent as an empty string: servers
        reject that as ``InvalidParams``. The task's configs are listed
        instead, and the single config is returned when there is exactly one.

        Args:
            task_id: ID of the task
            config_id: Optional specific config ID to retrieve

        Returns:
            The push notification configuration

        Raises:
            PushConfigNotFoundError: If the task has no push configs.
            PushConfigAmbiguousError: If the task has several configs and
                ``config_id`` was omitted.
        """
        validate_resource_id(task_id, "task_id")
        if config_id:
            validate_resource_id(config_id, "config_id")
            client = await self._get_or_create_client()
            request = GetTaskPushNotificationConfigRequest(
                task_id=task_id,
                id=config_id,
            )
            logger.info("Getting push config %s for task %s", config_id, task_id)
            return await client.get_task_push_notification_config(request)

        configs = await self.list_all_push_configs(task_id)
        if not configs:
            raise PushConfigNotFoundError(
                f"Task {task_id} has no push notification config"
            )
        if len(configs) > 1:
            ids = ", ".join(config.id or "(unnamed)" for config in configs)
            raise PushConfigAmbiguousError(
                f"Task {task_id} has {len(configs)} push notification configs "
                f"({ids}); specify config_id to choose one"
            )

        logger.info("Getting the only push config for task %s", task_id)
        return configs[0]

    async def list_push_configs(
        self,
        task_id: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> ListTaskPushNotificationConfigsResponse:
        """List a task's push notification configs, one page at a time.

        Args:
            task_id: ID of the task
            page_size: Maximum configs per page (server may return fewer);
                defaults to ``DEFAULT_PUSH_CONFIG_PAGE_SIZE``
            page_token: Continuation token from a previous page's
                ``next_page_token``

        Returns:
            The raw response with configs and the next page token.
        """
        validate_resource_id(task_id, "task_id")
        if page_token:
            reject_control_chars(page_token, "page_token")

        client = await self._get_or_create_client()

        # An unset proto3 int is indistinguishable from 0, and servers reject a
        # zero page size, so always send an explicit one.
        request = ListTaskPushNotificationConfigsRequest(
            task_id=task_id,
            page_size=page_size or DEFAULT_PUSH_CONFIG_PAGE_SIZE,
            page_token=page_token or "",
        )
        logger.info("Listing push configs for task %s", task_id)

        return await client.list_task_push_notification_configs(request)

    async def list_all_push_configs(
        self,
        task_id: str,
        page_size: int | None = None,
    ) -> list[TaskPushNotificationConfig]:
        """List a task's push configs across every page.

        A repeated token stops the loop, so a server that keeps returning the
        same page cannot spin this forever.
        """
        configs: list[TaskPushNotificationConfig] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()

        while True:
            response = await self.list_push_configs(
                task_id,
                page_size=page_size,
                page_token=page_token,
            )
            configs.extend(response.configs)
            page_token = response.next_page_token
            if not page_token or page_token in seen_tokens:
                break
            seen_tokens.add(page_token)

        logger.info("Listed %d push config(s) for task %s", len(configs), task_id)
        return configs

    async def delete_push_config(self, task_id: str, config_id: str) -> None:
        """Delete a push notification config from a task.

        The config is listed first: servers commonly accept a delete for a
        config that never existed, and that silence would hide a mistyped ID.

        Args:
            task_id: ID of the task
            config_id: ID of the config to delete

        Raises:
            PushConfigNotFoundError: If no such config exists on the task.
        """
        validate_resource_id(task_id, "task_id")
        validate_resource_id(config_id, "config_id")

        existing = await self.list_all_push_configs(task_id)
        if all(config.id != config_id for config in existing):
            raise PushConfigNotFoundError(
                f"Task {task_id} has no push notification config '{config_id}'"
            )

        client = await self._get_or_create_client()

        request = DeleteTaskPushNotificationConfigRequest(
            task_id=task_id,
            id=config_id,
        )
        logger.info("Deleting push config %s for task %s", config_id, task_id)

        await client.delete_task_push_notification_config(request)
