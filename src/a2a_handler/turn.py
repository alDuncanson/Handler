"""Driving a single agent turn.

A *turn* is one user message and everything the agent sends back in reply: a
stream of status changes and artifacts, ending either because the task reached
a terminal state or because the agent handed control back to the client.

This module owns the protocol semantics of that exchange -- when a turn is
over, which task a follow-up should continue, and what to do when the server
refuses to continue a saved task. It has no dependency on any user interface,
so the CLI, the TUI, and the MCP bridge can all drive a turn the same way and
the rules stay in one testable place.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum

from a2a.client.errors import A2AClientError
from a2a.types import Artifact, Message, Task

from a2a_handler.common import get_logger
from a2a_handler.service import (
    A2AService,
    StreamEvent,
    continuation_task_id,
    response_context_id,
    response_state,
    state_is_settled,
    state_needs_auth,
    state_needs_input,
)

logger = get_logger(__name__)

_UNCONTINUABLE_MARKERS = (
    "terminal state",
    "cannot accept further messages",
    "already completed",
    "task is completed",
)


def is_uncontinuable_task_error(error: Exception) -> bool:
    """Return whether the server refused to continue the referenced task.

    Servers phrase this differently, so this matches on the shapes seen in
    practice rather than an error code the protocol does not define.
    """
    if not isinstance(error, A2AClientError):
        return False
    message = str(error).lower()
    if "task" in message and ("does not exist" in message or "not found" in message):
        return True
    return any(marker in message for marker in _UNCONTINUABLE_MARKERS)


class TurnEventKind(str, Enum):
    """What a consumer needs to react to while a turn is in flight."""

    STATUS = "status"
    ARTIFACT = "artifact"
    MESSAGE = "message"
    NOTICE = "notice"


@dataclass(frozen=True, slots=True)
class TurnEvent:
    """Something worth showing the user while the turn is still running."""

    kind: TurnEventKind
    state: int | None = None
    task: Task | None = None
    artifact: Artifact | None = None
    message: Message | None = None
    text: str = ""


@dataclass(frozen=True, slots=True)
class TurnResult:
    """How a turn ended and what the client should do next."""

    response: Task | Message | None = None
    state: int | None = None
    context_id: str | None = None
    continue_task_id: str | None = None
    awaiting_input: bool = False
    awaiting_auth: bool = False
    canceled: bool = False
    error: Exception | None = None
    #: The last thing the agent said while the turn was running. A turn that
    #: is canceled or interrupted often leaves no text on the task itself, so
    #: this is what the user has to go on -- without it a stopped task reads
    #: as "no text in response" right after they watched it narrate.
    narration: str = ""

    @property
    def failed(self) -> bool:
        """Return whether the turn ended because of a client-side error."""
        return self.error is not None


@dataclass(slots=True)
class AgentTurn:
    """One user message and the agent's streamed reply.

    Iterate :meth:`events` to drive the turn; read :attr:`result` once the
    iteration finishes. Call :meth:`request_cancel` from another task to ask
    the agent to stop.
    """

    service: A2AService
    text: str
    context_id: str | None = None
    task_id: str | None = None

    result: TurnResult | None = None
    _task_id_seen: str | None = field(default=None, init=False)
    _cancel_requested: bool = field(default=False, init=False)
    _last_narration: str = field(default="", init=False)

    @property
    def active_task_id(self) -> str | None:
        """Return the task ID the agent reported for this turn, once known."""
        return self._task_id_seen

    async def request_cancel(self) -> bool:
        """Ask the agent to cancel this turn's task.

        Returns whether a cancel was actually sent. A turn that has not yet
        been assigned a task ID has nothing to cancel protocol-side; the
        caller should still stop consuming the stream.
        """
        self._cancel_requested = True
        task_id = self._task_id_seen
        if not task_id:
            logger.info("Cancel requested before a task ID was known")
            return False
        try:
            await self.service.cancel_task(task_id)
        except Exception as error:  # noqa: BLE001 - surfaced to the user, not raised
            logger.warning("Cancel request for task %s failed: %s", task_id, error)
            return False
        logger.info("Cancel requested for task %s", task_id)
        return True

    async def events(self) -> AsyncIterator[TurnEvent]:
        """Run the turn, yielding events until it settles."""
        try:
            async for event in self._stream_with_retry():
                yield event
        except asyncio.CancelledError:
            self.result = TurnResult(
                context_id=self.context_id,
                continue_task_id=self._task_id_seen,
                canceled=True,
                narration=self._last_narration,
            )
            raise
        except Exception as error:  # noqa: BLE001 - reported as a result, not raised
            logger.error("Turn failed: %s", error, exc_info=True)
            self.result = TurnResult(
                context_id=self.context_id,
                continue_task_id=self.task_id,
                error=error,
            )

    async def _stream_with_retry(self) -> AsyncIterator[TurnEvent]:
        """Stream the turn, retrying once without a task ID if the server balks.

        A saved task can go stale between sessions. Rather than failing the
        message, drop the task reference and retry within the same context --
        the conversation continues, only the task thread restarts.
        """
        try:
            async for event in self._stream(self.task_id):
                yield event
            return
        except Exception as error:  # noqa: BLE001 - inspected, then re-raised
            if not (self.task_id and is_uncontinuable_task_error(error)):
                raise
            logger.info("Retrying turn without stale task_id %s", self.task_id)

        yield TurnEvent(
            kind=TurnEventKind.NOTICE,
            text=(
                "The saved task can no longer accept messages. "
                "Continuing with the saved conversation only."
            ),
        )
        self.task_id = None
        async for event in self._stream(None):
            yield event

    async def _stream(self, task_id: str | None) -> AsyncIterator[TurnEvent]:
        """Consume one streaming attempt and translate it into turn events."""
        latest: Task | Message | None = None
        latest_state: int | None = None

        async for event in self.service.stream(
            self.text,
            context_id=self.context_id,
            task_id=task_id,
        ):
            if event.task_id:
                self._task_id_seen = event.task_id
            if event.context_id:
                self.context_id = event.context_id

            if event.text:
                self._last_narration = event.text

            for turn_event in self._translate(event):
                yield turn_event

            if event.task is not None:
                latest = event.task
            elif event.message is not None:
                latest = event.message

            if event.state is not None:
                latest_state = event.state
                if state_is_settled(event.state):
                    break

            # A cancel that the agent has acknowledged arrives as a CANCELED
            # status and settles above. This covers the agent that keeps
            # streaming regardless: stop consuming rather than ignore the user.
            if self._cancel_requested:
                logger.info("Stopping turn consumption after cancel request")
                break

        self.result = self._settle(latest, latest_state)

    def _translate(self, event: StreamEvent) -> list[TurnEvent]:
        """Translate one SDK stream event into zero or more turn events.

        Dispatches on ``event_type`` rather than on which fields are populated:
        every event carries the running task aggregate, so a field-presence
        check would report a status change on every artifact chunk.
        """
        if event.event_type == "artifact":
            update = event.artifact
            if update is None or not update.HasField("artifact"):
                return []
            return [
                TurnEvent(
                    kind=TurnEventKind.ARTIFACT,
                    artifact=update.artifact,
                    task=event.task,
                    state=event.state,
                    text=event.text,
                )
            ]

        if event.event_type == "message":
            return [
                TurnEvent(
                    kind=TurnEventKind.MESSAGE,
                    message=event.message,
                    text=event.text,
                )
            ]

        # "task" and "status" both describe where the task now stands.
        return [
            TurnEvent(
                kind=TurnEventKind.STATUS,
                state=event.state,
                task=event.task,
                text=event.text,
            )
        ]

    def _settle(
        self,
        response: Task | Message | None,
        fallback_state: int | None,
    ) -> TurnResult:
        """Build the result describing how this turn ended."""
        if response is None:
            return TurnResult(
                state=fallback_state,
                context_id=self.context_id,
                continue_task_id=self._task_id_seen,
                canceled=self._cancel_requested,
                narration=self._last_narration,
            )

        state = response_state(response) or fallback_state
        return TurnResult(
            response=response,
            state=state,
            context_id=response_context_id(response) or self.context_id,
            continue_task_id=(
                continuation_task_id(response) or self._continue_from(state)
            ),
            awaiting_input=state_needs_input(state),
            awaiting_auth=state_needs_auth(state),
            canceled=self._cancel_requested,
            narration=self._last_narration,
        )

    def _continue_from(self, state: int | None) -> str | None:
        """Fall back to the observed task ID when the task is still open."""
        if state_is_settled(state) and not state_needs_input(state):
            return None
        return self._task_id_seen


def summarize_result(result: TurnResult) -> str:
    """Return a short line describing an ended turn, for logs and notices."""
    if result.error is not None:
        return f"failed: {result.error}"
    if result.canceled:
        return "canceled"
    if result.awaiting_input:
        return "waiting for your reply"
    if result.awaiting_auth:
        return "waiting for authentication"
    return "done"


__all__ = [
    "AgentTurn",
    "TurnEvent",
    "TurnEventKind",
    "TurnResult",
    "is_uncontinuable_task_error",
    "summarize_result",
]
