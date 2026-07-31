"""Protobuf builders for A2A v1.0 SDK types used across the test suite.

The a2a-sdk 1.x exposes ``a2a.types`` as protobuf messages (not Pydantic
models). These helpers centralize the v1.0 construction idioms so individual
tests do not have to repeat them:

* ``Part`` is flat: ``Part(text=...)``, ``Part(data=<Value>)``,
  ``Part(url=...)`` / ``Part(raw=...)`` (``TextPart``/``DataPart``/``FilePart``
  are removed).
* Enums are protobuf ints: ``Role.ROLE_USER``, ``TaskState.TASK_STATE_*``.
* Proto string fields reject ``None`` -> pass ``""`` (handled here via ``or ""``).
* ``TaskPushNotificationConfig`` is flat (``url``/``token`` live on it directly).
* ``AgentCard`` has no top-level ``url`` -> use ``supported_interfaces``.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from typing import Any

from a2a import helpers
from a2a.client.card_resolver import parse_agent_card
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Artifact,
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskPushNotificationConfig,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

from a2a_handler.service import FetchedAgentCard, to_json_dict

__all__ = [
    "make_text_part",
    "make_data_part",
    "make_file_part",
    "make_message",
    "make_task",
    "make_artifact",
    "make_status_update_event",
    "make_artifact_update_event",
    "make_push_config",
    "make_agent_card",
    "make_stream_response",
    "make_fetched_card",
    "make_served_card",
    "stub_service_card",
]


def make_text_part(text: str) -> Part:
    """Build a text ``Part``."""
    return Part(text=text)


def make_data_part(data: dict[str, Any]) -> Part:
    """Build a structured-data ``Part`` from a Python dict."""
    return helpers.new_data_part(data)


def make_file_part(
    *,
    url: str | None = None,
    raw: bytes | None = None,
    filename: str | None = None,
    media_type: str | None = None,
) -> Part:
    """Build a file ``Part`` carrying either a URI (``url``) or inline ``raw`` bytes."""
    kwargs: dict[str, Any] = {}
    if url is not None:
        kwargs["url"] = url
    if raw is not None:
        kwargs["raw"] = raw
    if filename is not None:
        kwargs["filename"] = filename
    if media_type is not None:
        kwargs["media_type"] = media_type
    return Part(**kwargs)


def make_message(
    *,
    text: str | None = None,
    parts: Sequence[Part] | None = None,
    role: Role = Role.ROLE_AGENT,
    message_id: str = "msg-1",
    context_id: str | None = None,
    task_id: str | None = None,
) -> Message:
    """Build a ``Message``. Provide either ``text`` or explicit ``parts``."""
    if parts is None:
        parts = [make_text_part(text or "")]
    return Message(
        message_id=message_id,
        role=role,
        parts=list(parts),
        context_id=context_id or "",
        task_id=task_id or "",
    )


def make_task(
    state: TaskState = TaskState.TASK_STATE_COMPLETED,
    task_id: str = "task-123",
    context_id: str = "ctx-123",
    *,
    history: Iterable[Message] | None = None,
    artifacts: Iterable[Artifact] | None = None,
) -> Task:
    """Build a ``Task`` with the given state."""
    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=state),
        history=list(history) if history is not None else None,
        artifacts=list(artifacts) if artifacts is not None else None,
    )


def make_artifact(
    artifact_id: str = "artifact-123",
    *,
    name: str = "Release Notes",
    description: str = "Rendered markdown output",
    text: str | None = "Artifact body text",
    parts: Sequence[Part] | None = None,
) -> Artifact:
    """Build an ``Artifact``. Provide either ``text`` or explicit ``parts``."""
    if parts is None:
        parts = [make_text_part(text or "")]
    return Artifact(
        artifact_id=artifact_id,
        name=name,
        description=description,
        parts=list(parts),
    )


def make_status_update_event(
    *,
    task_id: str,
    context_id: str,
    state: TaskState = TaskState.TASK_STATE_WORKING,
    message: Message | None = None,
) -> TaskStatusUpdateEvent:
    """Build a ``TaskStatusUpdateEvent`` (no ``final``/``kind`` fields in v1.0)."""
    status = TaskStatus(state=state)
    if message is not None:
        status.message.CopyFrom(message)
    return TaskStatusUpdateEvent(
        task_id=task_id,
        context_id=context_id,
        status=status,
    )


def make_artifact_update_event(
    *,
    task_id: str,
    context_id: str,
    artifact: Artifact,
    append: bool = False,
    last_chunk: bool = False,
) -> TaskArtifactUpdateEvent:
    """Build a ``TaskArtifactUpdateEvent``."""
    return TaskArtifactUpdateEvent(
        task_id=task_id,
        context_id=context_id,
        artifact=artifact,
        append=append,
        last_chunk=last_chunk,
    )


def make_push_config(
    *,
    task_id: str = "",
    url: str = "",
    token: str = "",
    config_id: str = "",
) -> TaskPushNotificationConfig:
    """Build a flat ``TaskPushNotificationConfig`` (``url``/``token`` live on it)."""
    return TaskPushNotificationConfig(
        task_id=task_id,
        url=url,
        token=token,
        id=config_id,
    )


def make_agent_card(
    *,
    name: str = "Test Agent",
    description: str = "A test agent",
    version: str = "",
    url: str = "http://localhost:8000",
    protocol_version: str = "1.0",
    streaming: bool = True,
    push_notifications: bool = False,
    skills: Sequence[AgentSkill] | None = None,
    default_input_modes: Sequence[str] = ("text",),
    default_output_modes: Sequence[str] = ("text",),
) -> AgentCard:
    """Build a v1.0 ``AgentCard`` with a single JSON-RPC interface."""
    return AgentCard(
        name=name,
        description=description,
        version=version,
        supported_interfaces=[
            AgentInterface(
                url=url,
                protocol_binding="JSONRPC",
                protocol_version=protocol_version,
            )
        ],
        capabilities=AgentCapabilities(
            streaming=streaming,
            push_notifications=push_notifications,
        ),
        default_input_modes=list(default_input_modes),
        default_output_modes=list(default_output_modes),
        skills=list(skills) if skills is not None else [],
    )


def make_stream_response(
    *,
    task: Task | None = None,
    message: Message | None = None,
    status_update: TaskStatusUpdateEvent | None = None,
    artifact_update: TaskArtifactUpdateEvent | None = None,
) -> StreamResponse:
    """Build a ``StreamResponse`` wrapping exactly one oneof payload."""
    if task is not None:
        return StreamResponse(task=task)
    if message is not None:
        return StreamResponse(message=message)
    if status_update is not None:
        return StreamResponse(status_update=status_update)
    if artifact_update is not None:
        return StreamResponse(artifact_update=artifact_update)
    raise ValueError("make_stream_response requires exactly one payload")


def make_served_card(raw: dict[str, Any]) -> FetchedAgentCard:
    """Build a ``FetchedAgentCard`` from served JSON the way a real fetch does.

    Runs the served JSON through the SDK parser (including its v0.3 -> v1.0
    compatibility shims) so tests see the same lossy typed card production
    code sees, paired with the untouched JSON.
    """
    return FetchedAgentCard(card=parse_agent_card(copy.deepcopy(raw)), raw=raw)


def make_fetched_card(
    card: AgentCard,
    raw: dict[str, Any] | None = None,
) -> FetchedAgentCard:
    """Pair a typed card with the JSON a server would have served it as.

    When ``raw`` is omitted the typed card is round-tripped, which is the
    lossless case. Pass ``raw`` explicitly to model a card carrying fields the
    v1.0 ``AgentCard`` cannot represent (a v0.3 top-level ``protocolVersion``,
    ``url`` or ``preferredTransport``).
    """
    return FetchedAgentCard(
        card=card, raw=raw if raw is not None else to_json_dict(card)
    )


def stub_service_card(
    mock_service: Any,
    card: AgentCard,
    raw: dict[str, Any] | None = None,
) -> FetchedAgentCard:
    """Point both card accessors of a mocked ``A2AService`` at one card.

    Production code reads the card through either ``get_card`` (typed only) or
    ``get_card_document`` (typed plus served JSON); stubbing both keeps a mock
    self-consistent regardless of which one the code under test calls.
    """
    document = make_fetched_card(card, raw)
    mock_service.get_card.return_value = document.card
    mock_service.get_card_document.return_value = document
    return document
