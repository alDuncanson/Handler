"""Message commands for sending messages to A2A agents."""

import asyncio
import json
from dataclasses import replace
from typing import Any
from typing import Optional

import click
from a2a.types import DataPart, FilePart, Message, Part, Role, TextPart

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    parse_header_string,
)
from a2a_handler.common import Output, get_logger
from a2a_handler.common.input_validation import (
    InputValidationError,
    parse_json_object,
    reject_control_chars,
    reject_unknown_keys,
    validate_agent_url,
    validate_resource_id,
    validate_webhook_url,
)
from a2a_handler.service import (
    A2AService,
    A2AResponse,
    StreamEvent,
    protocol_dump,
    response_context_id,
    response_state,
    response_task_id,
)
from a2a_handler.session import get_session, update_session

from ._helpers import (
    build_http_client,
    build_streaming_http_client,
    handle_client_error,
    handle_validation_error,
    resolve_agent_selection,
    resolve_selection_credentials,
)

log = get_logger(__name__)


@click.group()
def message() -> None:
    """Send messages to A2A agents."""
    pass


@message.command("send")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--text", "-t", help="Message text")
@click.option("--stream", is_flag=True, help="Stream responses in real-time")
@click.option(
    "--json",
    "json_payload",
    help="Raw JSON payload for agent-friendly invocation",
)
@click.option("--context-id", help="Context ID for conversation continuity")
@click.option("--task-id", help="Task ID to continue")
@click.option(
    "--continue", "-C", "use_session", is_flag=True, help="Continue from saved session"
)
@click.option("--push-url", help="Webhook URL for push notifications")
@click.option("--push-token", help="Authentication token for push notifications")
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
@click.option(
    "--header",
    "-H",
    "headers",
    multiple=True,
    help="Custom header (repeatable, format: 'Name: Value')",
)
def message_send(
    agent_url: Optional[str],
    server_name: Optional[str],
    text: Optional[str],
    stream: bool,
    json_payload: Optional[str],
    context_id: Optional[str],
    task_id: Optional[str],
    use_session: bool,
    push_url: Optional[str],
    push_token: Optional[str],
    bearer_env: Optional[str],
    api_key_env: Optional[str],
    headers: tuple[str, ...] = (),
) -> None:
    """Send a message to an agent and receive a response.

    \b
    Examples:
      $ handler message send --server my_agent --text "Hello"
      $ handler message send --url http://localhost:8000 --text "Hello"
      $ handler message send --server my_agent --text "Hello" --stream
      $ handler message send --server my_agent --text "Follow up" --continue
      $ handler message send --url http://localhost:8000 --bearer-env MY_TOKEN --text "Hi"
    """
    output = Output()
    payload: dict[str, Any] = {}

    selection = resolve_agent_selection(agent_url, server_name)
    resolved_url = selection.agent_url

    try:
        validate_agent_url(resolved_url)
        if json_payload:
            payload = parse_json_object(json_payload, "json_payload")
            reject_unknown_keys(
                payload,
                {
                    "text",
                    "message",
                    "stream",
                    "context_id",
                    "task_id",
                    "use_session",
                    "push_url",
                    "push_token",
                },
                "json_payload",
            )

        if text is None:
            text = payload.get("text") or payload.get("message")  # type: ignore[assignment]
            if not isinstance(text, str) or not text:
                raise InputValidationError(
                    code="missing_message_text",
                    message="Provide message text as argument or in --json payload",
                    suggestion='Pass --text or include {"text": "..."} in --json',
                )

        payload_context_id = payload.get("context_id")
        if not context_id and isinstance(payload_context_id, str):
            context_id = payload_context_id

        payload_task_id = payload.get("task_id")
        if not task_id and isinstance(payload_task_id, str):
            task_id = payload_task_id

        payload_stream = payload.get("stream")
        if not stream and isinstance(payload_stream, bool):
            stream = payload_stream

        payload_use_session = payload.get("use_session")
        if not use_session and isinstance(payload_use_session, bool):
            use_session = payload_use_session

        payload_push_url = payload.get("push_url")
        if not push_url and isinstance(payload_push_url, str):
            push_url = payload_push_url

        payload_push_token = payload.get("push_token")
        if not push_token and isinstance(payload_push_token, str):
            push_token = payload_push_token

        if context_id:
            validate_resource_id(context_id, "context_id")
        if task_id:
            validate_resource_id(task_id, "task_id")
        if push_url:
            validate_webhook_url(push_url)
        if push_token:
            reject_control_chars(push_token, "push_token")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    assert text is not None

    log.info("Sending message to %s", resolved_url)

    if use_session and not context_id:
        session = get_session(resolved_url)
        if session.context_id:
            try:
                validate_resource_id(session.context_id, "context_id")
            except InputValidationError as error:
                handle_validation_error(error, output)
                raise click.Abort() from error
            context_id = session.context_id
            if not task_id and session.task_id:
                try:
                    validate_resource_id(session.task_id, "task_id")
                except InputValidationError as error:
                    log.warning(
                        "Ignoring saved task_id for %s: %s",
                        resolved_url,
                        error.message,
                    )
                else:
                    task_id = session.task_id
            log.info("Using saved context: %s", context_id)

    custom_headers: dict[str, str] | None = None
    if headers:
        custom_headers = {}
        for h in headers:
            try:
                name, value = parse_header_string(h)
                reject_control_chars(name, "header name")
                reject_control_chars(value, "header value")
                custom_headers[name] = value
            except (ValueError, InputValidationError) as e:
                output.error(code="invalid_input", message=str(e))
                raise click.Abort() from e

    credentials = resolve_selection_credentials(selection, bearer_env, api_key_env)

    if custom_headers:
        if credentials is None:
            credentials = AuthCredentials(
                auth_type=AuthType.BEARER,
                custom_headers=custom_headers,
            )
        else:
            credentials = replace(credentials)
            merged = dict(credentials.custom_headers or {})
            merged.update(custom_headers)
            credentials.custom_headers = merged

    async def do_send() -> None:
        try:
            client_factory = (
                build_streaming_http_client if stream else build_http_client
            )
            async with client_factory(credentials=credentials) as http_client:
                service = A2AService(
                    http_client,
                    resolved_url,
                    enable_streaming=stream,
                    push_notification_url=push_url,
                    push_notification_token=push_token,
                    credentials=credentials,
                )

                if stream:
                    await _stream_message(
                        service, text, context_id, task_id, resolved_url, output
                    )
                else:
                    response = await service.send(text, context_id, task_id)
                    update_session(
                        resolved_url,
                        response_context_id(response),
                        response_task_id(response),
                    )
                    _format_response(response, output)

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_send())


@message.command("stream")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--text", "-t", required=True, help="Message text")
@click.option("--context-id", help="Context ID for conversation continuity")
@click.option("--task-id", help="Task ID to continue")
@click.option(
    "--continue", "-C", "use_session", is_flag=True, help="Continue from saved session"
)
@click.option("--push-url", help="Webhook URL for push notifications")
@click.option("--push-token", help="Authentication token for push notifications")
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
@click.option(
    "--header",
    "-H",
    "headers",
    multiple=True,
    help="Custom header (repeatable, format: 'Name: Value')",
)
@click.pass_context
def message_stream(
    ctx: click.Context,
    agent_url: Optional[str],
    server_name: Optional[str],
    text: str,
    context_id: Optional[str],
    task_id: Optional[str],
    use_session: bool,
    push_url: Optional[str],
    push_token: Optional[str],
    bearer_env: Optional[str],
    api_key_env: Optional[str],
    headers: tuple[str, ...] = (),
) -> None:
    """Send a message and stream the response in real-time.

    \b
    Examples:
      $ handler message stream --server my_agent --text "Hello"
      $ handler message stream --url http://localhost:8000 --text "Hello"
      $ handler message stream --server my_agent --text "Follow up" --continue
    """
    ctx.invoke(
        message_send,
        agent_url=agent_url,
        server_name=server_name,
        text=text,
        stream=True,
        context_id=context_id,
        task_id=task_id,
        use_session=use_session,
        push_url=push_url,
        push_token=push_token,
        bearer_env=bearer_env,
        api_key_env=api_key_env,
        headers=headers,
    )


async def _stream_message(
    service: A2AService,
    text: str,
    context_id: Optional[str],
    task_id: Optional[str],
    agent_url: str,
    output: Output,
) -> None:
    """Stream a message and handle events."""
    last_context_id: str | None = None
    last_task_id: str | None = None
    last_response: A2AResponse | None = None
    emitted_text = ""
    emitted_summaries: set[str] = set()
    text_line_open = False
    separated_text_from_events = False
    last_output_was_text = False
    emitted_full_task_id: str | None = None

    async for event in service.stream(text, context_id, task_id):
        last_context_id = event.context_id or last_context_id
        last_task_id = event.task_id or last_task_id
        if event.task:
            last_response = event.task
        elif event.message:
            last_response = event.message

        if output.output_format == "ndjson":
            output.json(_stream_event_dump(event))
        elif output.output_format == "text":
            if event.task_id and emitted_full_task_id is None:
                output.text(f"task id: {event.task_id}", flush=True)
                emitted_full_task_id = event.task_id

            for summary in _format_stream_event_summaries(event):
                if summary in emitted_summaries:
                    continue
                if text_line_open:
                    output.text(flush=True)
                    text_line_open = False
                if last_output_was_text:
                    output.text(flush=True)
                output.text(summary, flush=True)
                emitted_summaries.add(summary)
                last_output_was_text = False

            event_text = _format_stream_event_text(event)
            if event_text:
                text_to_emit = _stream_text_delta(emitted_text, event_text)
                if text_to_emit:
                    if emitted_summaries and not separated_text_from_events:
                        output.text(flush=True)
                        separated_text_from_events = True
                    output.text(text_to_emit, end="", flush=True)
                    emitted_text += text_to_emit
                    text_line_open = not text_to_emit.endswith("\n")
                    last_output_was_text = True

    update_session(agent_url, last_context_id, last_task_id)

    if last_response:
        if output.output_format == "json":
            output.json(protocol_dump(last_response))
        elif output.output_format == "text":
            if emitted_text:
                if text_line_open:
                    output.text()
            else:
                output.text(_format_response_text(last_response))
    else:
        output.error(code="no_response", message="No response received from stream")


def _format_response(response: A2AResponse, output: Output) -> None:
    """Format and display an A2A response."""
    if output.is_structured:
        output.json(protocol_dump(response))
    else:
        output.text(_format_response_text(response))


def _format_response_text(response: A2AResponse) -> str:
    """Format an A2A response as human-readable text."""
    text = _format_response_parts(response)
    if text:
        return text

    lines: list[str] = []
    state = response_state(response)
    if state:
        lines.append(f"State: {state.value}")
    context_id = response_context_id(response)
    if context_id:
        lines.append(f"Context ID: {context_id}")
    task_id = response_task_id(response)
    if task_id:
        lines.append(f"Task ID: {task_id}")
    if not lines:
        lines.append("No text response received.")
    return "\n".join(lines)


def _format_response_parts(response: A2AResponse) -> str:
    """Format response parts for human-readable CLI output."""
    if isinstance(response, Message):
        return _format_message_parts(response)

    formatted_parts: list[str] = []
    if response.artifacts:
        for artifact in response.artifacts:
            formatted = _format_parts(artifact.parts)
            if formatted:
                formatted_parts.append(formatted)

    if not formatted_parts and response.history:
        for message in response.history:
            if message.role == Role.agent:
                formatted = _format_message_parts(message)
                if formatted:
                    formatted_parts.append(formatted)

    return "\n\n".join(formatted_parts)


def _format_stream_event_text(event: StreamEvent) -> str:
    """Format a streaming event for human-readable text output."""
    if event.message:
        return _format_message_parts(event.message)

    if event.status and event.status.status and event.status.status.message:
        return _format_message_parts(event.status.status.message)

    if event.artifact and event.artifact.artifact:
        return _format_parts(event.artifact.artifact.parts)

    if event.event_type == "task" and event.task:
        return _format_response_parts(event.task)

    return event.text


def _format_stream_event_summaries(event: StreamEvent) -> list[str]:
    """Return lightweight event summaries for human-readable stream output."""
    summaries: list[str] = []

    if event.state:
        summaries.append(
            _format_event_summary("task", event.state.value, event.task_id)
        )

    parts = _stream_event_parts(event)
    for part in parts:
        summaries.extend(_format_part_event_summaries(part, event.task_id))

    if event.event_type == "artifact" and not summaries:
        summaries.append(_format_event_summary("artifact", "updated", event.task_id))

    return summaries


def _stream_event_parts(event: StreamEvent) -> list[Part]:
    """Return the parts carried by a stream event, if any."""
    if event.message and event.message.role == Role.agent:
        return event.message.parts or []
    if event.status and event.status.status and event.status.status.message:
        message = event.status.status.message
        if message.role == Role.agent:
            return message.parts or []
    if event.artifact and event.artifact.artifact:
        return event.artifact.artifact.parts or []
    return []


def _format_part_event_summaries(part: Part, task_id: str | None) -> list[str]:
    """Summarize a stream part without rendering its full content."""
    root = part.root
    if isinstance(root, TextPart):
        return [_format_event_summary("message", "text", task_id)]
    if isinstance(root, DataPart):
        if _is_tool_call_data(root.data):
            return [
                _format_event_summary(
                    "tool call", str(root.data.get("name", "unknown")), task_id
                )
            ]
        if _is_tool_response_data(root.data):
            return [
                _format_event_summary(
                    "tool result", str(root.data.get("name", "unknown")), task_id
                )
            ]
        return [_format_event_summary("message", "data", task_id)]
    if isinstance(root, FilePart):
        return [_format_event_summary("message", "file", task_id)]
    return [_format_event_summary("message", getattr(root, "kind", "part"), task_id)]


def _format_event_summary(kind: str, detail: str, task_id: str | None) -> str:
    """Format one human-readable stream event summary."""
    task_suffix = f" ({_short_id(task_id)})" if task_id else ""
    return f"event: {kind} {detail}{task_suffix}"


def _short_id(value: str | None) -> str:
    """Return a compact identifier for stream summaries."""
    if not value:
        return ""
    return value[:8]


def _stream_text_delta(emitted_text: str, event_text: str) -> str:
    """Return only the not-yet-emitted portion of a stream text event."""
    if not emitted_text:
        return event_text
    if event_text == emitted_text or event_text in emitted_text:
        return ""
    if event_text.startswith(emitted_text):
        return event_text[len(emitted_text) :]
    return event_text


def _format_message_parts(message: Message) -> str:
    """Format a protocol message's parts, skipping echoed user messages."""
    if message.role != Role.agent:
        return ""
    return _format_parts(message.parts)


def _format_parts(parts: list[Part] | None) -> str:
    """Format A2A message/artifact parts for human-readable CLI output."""
    if not parts:
        return ""

    formatted_parts: list[str] = []
    for part in parts:
        formatted = _format_part(part)
        if formatted:
            formatted_parts.append(formatted)
    return "\n\n".join(formatted_parts)


def _format_part(part: Part) -> str:
    """Format a single A2A part for human-readable CLI output."""
    root = part.root
    if isinstance(root, TextPart):
        return root.text
    if isinstance(root, DataPart):
        return _format_data_part(root)
    if isinstance(root, FilePart):
        return _format_file_part(root)

    return "```json\n" + json.dumps(part.model_dump(mode="json"), indent=2) + "\n```"


def _format_data_part(part: DataPart) -> str:
    """Format structured data parts while hiding internal tool chatter."""
    data = part.data
    if _is_tool_call_data(data) or _is_tool_response_data(data):
        return ""
    return "```json\n" + json.dumps(data, indent=2, default=str) + "\n```"


def _is_tool_call_data(data: dict[str, Any]) -> bool:
    """Return whether a data part looks like an internal tool call."""
    return {"id", "name", "args"}.issubset(data)


def _is_tool_response_data(data: dict[str, Any]) -> bool:
    """Return whether a data part looks like an internal tool response."""
    return {"id", "name", "response"}.issubset(data)


def _format_file_part(part: FilePart) -> str:
    """Format file parts without dumping inline bytes into the terminal."""
    file_part = part.file
    name = getattr(file_part, "name", None) or "unnamed file"
    mime_type = getattr(file_part, "mime_type", None)
    uri = getattr(file_part, "uri", None)
    inline_bytes = getattr(file_part, "bytes", None)

    details = [name]
    if mime_type:
        details.append(mime_type)
    if uri:
        details.append(uri)
    elif inline_bytes:
        details.append(f"inline bytes, {len(inline_bytes)} base64 chars")
    return "[file: " + ", ".join(details) + "]"


def _stream_event_dump(event: StreamEvent) -> dict[str, object]:
    """Serialize a streaming event for NDJSON output."""
    data: dict[str, object] = {"type": event.event_type}
    if event.context_id:
        data["contextId"] = event.context_id
    if event.task_id:
        data["taskId"] = event.task_id
    if event.state:
        data["state"] = event.state.value
    if event.text:
        data["text"] = event.text
    if event.message:
        data["message"] = protocol_dump(event.message)
    if event.task:
        data["task"] = protocol_dump(event.task)
    return data
