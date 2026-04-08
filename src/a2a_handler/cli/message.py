"""Message commands for sending messages to A2A agents."""

import asyncio
from dataclasses import replace
from typing import Any
from typing import Optional

import click

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
    protocol_dump,
    response_context_id,
    response_task_id,
)
from a2a_handler.session import get_session, update_session

from ._helpers import (
    build_http_client,
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
            async with build_http_client(credentials=credentials) as http_client:
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

    async for event in service.stream(text, context_id, task_id):
        last_context_id = event.context_id or last_context_id
        last_task_id = event.task_id or last_task_id
        if event.task:
            last_response = event.task
        elif event.message:
            last_response = event.message

    update_session(agent_url, last_context_id, last_task_id)

    if last_response:
        output.json(protocol_dump(last_response))
    else:
        output.error(code="no_response", message="No response received from stream")


def _format_response(response: A2AResponse, output: Output) -> None:
    """Format and display an A2A response."""
    output.json(protocol_dump(response))
