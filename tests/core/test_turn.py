"""Tests for driving a single agent turn."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Sequence
from unittest.mock import AsyncMock

import pytest
from a2a.client.errors import A2AClientError
from a2a.types import TaskState

from a2a_handler.service import StreamEvent
from a2a_handler.turn import (
    AgentTurn,
    TurnEventKind,
    is_uncontinuable_task_error,
    summarize_result,
)
from tests.factories import (
    make_artifact,
    make_artifact_update_event,
    make_message,
    make_status_update_event,
    make_task,
)

TASK_ID = "task-123"
CTX_ID = "ctx-123"


def _status_event(state: TaskState, text: str = "") -> StreamEvent:
    """Build a Handler stream event carrying a status change."""
    task = make_task(state=state, task_id=TASK_ID, context_id=CTX_ID)
    return StreamEvent(
        event_type="status",
        task=task,
        status=make_status_update_event(
            task_id=TASK_ID, context_id=CTX_ID, state=state
        ),
        text=text,
    )


def _artifact_event(artifact_id: str = "artifact-1") -> StreamEvent:
    """Build a Handler stream event carrying an artifact update."""
    artifact = make_artifact(artifact_id=artifact_id)
    return StreamEvent(
        event_type="artifact",
        task=make_task(
            state=TaskState.TASK_STATE_WORKING, task_id=TASK_ID, context_id=CTX_ID
        ),
        artifact=make_artifact_update_event(
            task_id=TASK_ID, context_id=CTX_ID, artifact=artifact
        ),
        text="Artifact body text",
    )


def _service_streaming(
    events: Sequence[StreamEvent],
    *,
    fail_first_with: Exception | None = None,
) -> AsyncMock:
    """Build a service double whose ``stream`` replays the given events.

    When ``fail_first_with`` is set the first call raises it, letting tests
    exercise the retry path.
    """
    service = AsyncMock()
    calls: list[str | None] = []

    def stream(text, *, context_id=None, task_id=None):  # noqa: ANN001, ARG001
        calls.append(task_id)

        async def gen() -> AsyncIterator[StreamEvent]:
            if fail_first_with is not None and len(calls) == 1:
                raise fail_first_with
            for event in events:
                yield event

        return gen()

    service.stream = stream
    service.stream_calls = calls
    return service


async def _drain(turn: AgentTurn) -> list:
    """Consume a turn's events into a list."""
    return [event async for event in turn.events()]


class TestTurnCompletion:
    """A turn that runs to a terminal state."""

    async def test_yields_status_and_artifact_events(self):
        service = _service_streaming(
            [
                _status_event(TaskState.TASK_STATE_WORKING, "thinking"),
                _artifact_event(),
                _status_event(TaskState.TASK_STATE_COMPLETED, "done"),
            ]
        )
        turn = AgentTurn(service=service, text="hi")

        events = await _drain(turn)

        kinds = [event.kind for event in events]
        assert kinds == [
            TurnEventKind.STATUS,
            TurnEventKind.ARTIFACT,
            TurnEventKind.STATUS,
        ]
        assert events[1].artifact is not None
        assert events[1].artifact.artifact_id == "artifact-1"

    async def test_result_reports_completion_and_clears_task(self):
        service = _service_streaming([_status_event(TaskState.TASK_STATE_COMPLETED)])
        turn = AgentTurn(service=service, text="hi")

        await _drain(turn)

        assert turn.result is not None
        assert turn.result.state == TaskState.TASK_STATE_COMPLETED
        assert turn.result.context_id == CTX_ID
        # A completed task cannot take more messages.
        assert turn.result.continue_task_id is None
        assert turn.result.awaiting_input is False
        assert turn.result.failed is False

    async def test_stops_at_terminal_state_without_draining_rest(self):
        """A settled state ends the turn even if the server keeps talking."""
        service = _service_streaming(
            [
                _status_event(TaskState.TASK_STATE_COMPLETED),
                _status_event(TaskState.TASK_STATE_WORKING),
            ]
        )
        turn = AgentTurn(service=service, text="hi")

        events = await _drain(turn)

        assert len(events) == 1
        assert turn.result is not None
        assert turn.result.state == TaskState.TASK_STATE_COMPLETED


class TestInputRequired:
    """The state that previously hung the client."""

    async def test_input_required_settles_the_turn(self):
        service = _service_streaming(
            [
                _status_event(TaskState.TASK_STATE_WORKING),
                _status_event(TaskState.TASK_STATE_INPUT_REQUIRED, "Which region?"),
            ]
        )
        turn = AgentTurn(service=service, text="deploy")

        events = await _drain(turn)

        assert turn.result is not None
        assert turn.result.awaiting_input is True
        assert events[-1].text == "Which region?"

    async def test_input_required_keeps_the_task_for_the_reply(self):
        """The follow-up must continue the same task, not start a new one."""
        service = _service_streaming(
            [_status_event(TaskState.TASK_STATE_INPUT_REQUIRED)]
        )
        turn = AgentTurn(service=service, text="deploy")

        await _drain(turn)

        assert turn.result is not None
        assert turn.result.continue_task_id == TASK_ID

    async def test_auth_required_settles_and_flags(self):
        service = _service_streaming(
            [_status_event(TaskState.TASK_STATE_AUTH_REQUIRED)]
        )
        turn = AgentTurn(service=service, text="hi")

        await _drain(turn)

        assert turn.result is not None
        assert turn.result.awaiting_auth is True
        assert turn.result.continue_task_id == TASK_ID


class TestStaleTaskRetry:
    """A saved task that the server will no longer continue."""

    async def test_retries_without_task_id_and_notices(self):
        service = _service_streaming(
            [_status_event(TaskState.TASK_STATE_COMPLETED)],
            fail_first_with=A2AClientError("Task task-999 does not exist"),
        )
        turn = AgentTurn(service=service, text="hi", task_id="task-999")

        events = await _drain(turn)

        assert service.stream_calls == ["task-999", None]
        assert events[0].kind == TurnEventKind.NOTICE
        assert "saved task" in events[0].text.lower()
        assert turn.result is not None
        assert turn.result.failed is False

    async def test_other_errors_are_not_retried(self):
        service = _service_streaming(
            [], fail_first_with=A2AClientError("upstream exploded")
        )
        turn = AgentTurn(service=service, text="hi", task_id="task-999")

        await _drain(turn)

        assert service.stream_calls == ["task-999"]
        assert turn.result is not None
        assert turn.result.failed is True

    async def test_no_retry_when_there_was_no_task_id(self):
        service = _service_streaming(
            [], fail_first_with=A2AClientError("Task not found")
        )
        turn = AgentTurn(service=service, text="hi")

        await _drain(turn)

        assert service.stream_calls == [None]
        assert turn.result is not None
        assert turn.result.failed is True

    @pytest.mark.parametrize(
        "message,expected",
        [
            ("Task task-1 does not exist", True),
            ("task not found", True),
            ("Task is in a terminal state", True),
            ("cannot accept further messages", True),
            ("rate limited", False),
            ("connection reset", False),
        ],
    )
    def test_uncontinuable_error_detection(self, message, expected):
        assert is_uncontinuable_task_error(A2AClientError(message)) is expected

    def test_non_a2a_errors_are_never_uncontinuable(self):
        assert is_uncontinuable_task_error(ValueError("task not found")) is False


class TestCancel:
    """Protocol-level cancellation."""

    async def test_request_cancel_calls_the_service(self):
        service = _service_streaming([_status_event(TaskState.TASK_STATE_WORKING)])
        turn = AgentTurn(service=service, text="hi")
        await _drain(turn)

        sent = await turn.request_cancel()

        assert sent is True
        service.cancel_task.assert_awaited_once_with(TASK_ID)

    async def test_cancel_before_task_id_is_known_sends_nothing(self):
        service = _service_streaming([])
        turn = AgentTurn(service=service, text="hi")

        sent = await turn.request_cancel()

        assert sent is False
        service.cancel_task.assert_not_awaited()

    async def test_cancel_failure_is_reported_not_raised(self):
        service = _service_streaming([_status_event(TaskState.TASK_STATE_WORKING)])
        service.cancel_task.side_effect = A2AClientError("not cancelable")
        turn = AgentTurn(service=service, text="hi")
        await _drain(turn)

        sent = await turn.request_cancel()

        assert sent is False

    async def test_worker_cancellation_records_a_canceled_result(self):
        """Cancelling the consuming task still leaves a usable result."""
        started = asyncio.Event()

        def stream(text, *, context_id=None, task_id=None):  # noqa: ANN001, ARG001
            async def gen() -> AsyncIterator[StreamEvent]:
                yield _status_event(TaskState.TASK_STATE_WORKING)
                started.set()
                await asyncio.sleep(30)

            return gen()

        service = AsyncMock()
        service.stream = stream
        turn = AgentTurn(service=service, text="hi")

        async def consume() -> None:
            async for _ in turn.events():
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert turn.result is not None
        assert turn.result.canceled is True
        assert turn.result.continue_task_id == TASK_ID


class TestSummarize:
    """The one-line description used for notices and logs."""

    @pytest.mark.parametrize(
        "state,expected",
        [
            (TaskState.TASK_STATE_COMPLETED, "done"),
            (TaskState.TASK_STATE_INPUT_REQUIRED, "waiting for your reply"),
            (TaskState.TASK_STATE_AUTH_REQUIRED, "waiting for authentication"),
        ],
    )
    async def test_summaries(self, state, expected):
        service = _service_streaming([_status_event(state)])
        turn = AgentTurn(service=service, text="hi")
        await _drain(turn)

        assert turn.result is not None
        assert summarize_result(turn.result) == expected

    async def test_error_summary_includes_the_cause(self):
        service = _service_streaming([], fail_first_with=A2AClientError("boom"))
        turn = AgentTurn(service=service, text="hi")
        await _drain(turn)

        assert turn.result is not None
        assert "boom" in summarize_result(turn.result)


class TestStandaloneMessage:
    """Agents may reply with a Message instead of a Task."""

    async def test_message_only_reply_settles(self):
        message = make_message(text="hello back", context_id=CTX_ID)
        service = _service_streaming(
            [StreamEvent(event_type="message", message=message, text="hello back")]
        )
        turn = AgentTurn(service=service, text="hi")

        events = await _drain(turn)

        assert events[0].kind == TurnEventKind.MESSAGE
        assert turn.result is not None
        assert turn.result.response is message
        assert turn.result.failed is False


class TestStatusMessageFallback:
    """A task whose only text is on its status message."""

    async def test_paused_task_text_comes_from_the_status_message(self):
        """An agent asking a question often carries it only on the status."""
        from a2a.types import TaskStatus

        from a2a_handler.service import extract_text_from_task

        task = make_task(state=TaskState.TASK_STATE_INPUT_REQUIRED)
        task.ClearField("artifacts")
        task.ClearField("history")
        task.status.CopyFrom(
            TaskStatus(
                state=TaskState.TASK_STATE_INPUT_REQUIRED,
                message=make_message(text="Which region?"),
            )
        )

        assert extract_text_from_task(task) == "Which region?"

    async def test_artifacts_still_win_over_the_status_message(self):
        """The fallback must not displace the task's real output."""
        from a2a.types import TaskStatus

        from a2a_handler.service import extract_text_from_task

        task = make_task(
            state=TaskState.TASK_STATE_COMPLETED,
            artifacts=[make_artifact(text="the real answer")],
        )
        task.status.CopyFrom(
            TaskStatus(
                state=TaskState.TASK_STATE_COMPLETED,
                message=make_message(text="incidental narration"),
            )
        )

        assert extract_text_from_task(task) == "the real answer"


class TestNarration:
    """What the agent last said, kept for turns that end with no text."""

    async def test_narration_survives_a_cancel(self):
        """A canceled task carries no text; the user should still see progress."""
        service = _service_streaming(
            [
                _status_event(TaskState.TASK_STATE_WORKING, "Working... step 4 of 40"),
                _status_event(TaskState.TASK_STATE_CANCELED),
            ]
        )
        turn = AgentTurn(service=service, text="slow")

        await _drain(turn)

        assert turn.result is not None
        assert turn.result.narration == "Working... step 4 of 40"

    async def test_narration_tracks_the_latest_text(self):
        service = _service_streaming(
            [
                _status_event(TaskState.TASK_STATE_WORKING, "first"),
                _status_event(TaskState.TASK_STATE_WORKING, "second"),
                _status_event(TaskState.TASK_STATE_COMPLETED, "third"),
            ]
        )
        turn = AgentTurn(service=service, text="hi")

        await _drain(turn)

        assert turn.result is not None
        assert turn.result.narration == "third"

    async def test_narration_survives_worker_cancellation(self):
        """Cancelling the consumer keeps whatever the agent had already said."""
        started = asyncio.Event()

        def stream(text, *, context_id=None, task_id=None):  # noqa: ANN001, ARG001
            async def gen() -> AsyncIterator[StreamEvent]:
                yield _status_event(TaskState.TASK_STATE_WORKING, "halfway there")
                started.set()
                await asyncio.sleep(30)

            return gen()

        service = AsyncMock()
        service.stream = stream
        turn = AgentTurn(service=service, text="slow")

        async def consume() -> None:
            async for _ in turn.events():
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert turn.result is not None
        assert turn.result.narration == "halfway there"
