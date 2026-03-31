"""Task commands for managing A2A tasks."""

import asyncio
from typing import Any
from typing import Optional

import click

from a2a_handler.auth import AuthCredentials, create_api_key_auth, create_bearer_auth
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
from a2a.types import Task
from a2a_handler.service import (
    A2AService,
    StreamEvent,
    extract_text,
    protocol_dump,
    response_context_id,
    response_state,
    response_task_id,
)

from ._helpers import (
    build_http_client,
    handle_client_error,
    handle_validation_error,
    resolve_agent_target,
)

log = get_logger(__name__)


@click.group()
def task() -> None:
    """Manage A2A tasks."""
    pass


@task.command("get")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", required=True, help="Task ID to retrieve")
@click.option(
    "--history-length", "-n", type=int, help="Number of history messages to include"
)
@click.option("--raw", is_flag=True, help="Emit full A2A protocol response")
@click.option(
    "--params",
    "json_params",
    help="Raw JSON params object for agent-friendly invocation",
)
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def task_get(
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: str,
    history_length: Optional[int],
    raw: bool,
    json_params: Optional[str],
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Retrieve the current status of a task.

    \b
    Examples:
      $ handler task get --server my_agent --task task-123
      $ handler task get --url http://localhost:8000 --task task-123
      $ handler task get --server my_agent --task task-123 --history-length 10
    """
    output = Output()
    payload: dict[str, Any] = {}

    resolved_url, resolved_credentials = resolve_agent_target(
        agent_url, server_name, bearer_token, api_key
    )

    try:
        validate_agent_url(resolved_url)
        if json_params:
            payload = parse_json_object(json_params, "params")
            reject_unknown_keys(
                payload,
                {"task_id", "history_length", "bearer_token", "api_key"},
                "params",
            )
        payload_task_id = payload.get("task_id")
        if isinstance(payload_task_id, str):
            task_id = payload_task_id

        payload_history_length = payload.get("history_length")
        if history_length is None and isinstance(payload_history_length, int):
            history_length = payload_history_length

        payload_bearer_token = payload.get("bearer_token")
        if not bearer_token and isinstance(payload_bearer_token, str):
            bearer_token = payload_bearer_token

        payload_api_key = payload.get("api_key")
        if not api_key and isinstance(payload_api_key, str):
            api_key = payload_api_key

        validate_resource_id(task_id, "task_id")
        if bearer_token:
            reject_control_chars(bearer_token, "bearer_token")
        if api_key:
            reject_control_chars(api_key, "api_key")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Getting task %s from %s", task_id, resolved_url)

    credentials = resolved_credentials

    async def do_get() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(
                    http_client, resolved_url, credentials=credentials
                )
                task = await service.get_task(task_id, history_length)
                _format_task(task, output, raw)
        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_get())


@task.command("cancel")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", required=True, help="Task ID to cancel")
@click.option("--raw", is_flag=True, help="Emit full A2A protocol response")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def task_cancel(
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: str,
    raw: bool,
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Request cancellation of a task.

    \b
    Examples:
      $ handler task cancel --server my_agent --task task-123
      $ handler task cancel --url http://localhost:8000 --task task-123
    """
    output = Output()

    resolved_url, resolved_credentials = resolve_agent_target(
        agent_url, server_name, bearer_token, api_key
    )

    try:
        validate_agent_url(resolved_url)
        validate_resource_id(task_id, "task_id")
        if bearer_token:
            reject_control_chars(bearer_token, "bearer_token")
        if api_key:
            reject_control_chars(api_key, "api_key")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Canceling task %s at %s", task_id, resolved_url)

    credentials = resolved_credentials

    async def do_cancel() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(
                    http_client, resolved_url, credentials=credentials
                )

                output.dim(f"Canceling task {task_id}...")

                task = await service.cancel_task(task_id)
                _format_task(task, output, raw)

                output.success("Task canceled")

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_cancel())


@task.command("resubscribe")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", required=True, help="Task ID to resubscribe to")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def task_resubscribe(
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: str,
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Resubscribe to a task's SSE stream after disconnection.

    \b
    Examples:
      $ handler task resubscribe --server my_agent --task task-123
      $ handler task resubscribe --url http://localhost:8000 --task task-123
    """
    output = Output()

    resolved_url, resolved_credentials = resolve_agent_target(
        agent_url, server_name, bearer_token, api_key
    )

    try:
        validate_agent_url(resolved_url)
        validate_resource_id(task_id, "task_id")
        if bearer_token:
            reject_control_chars(bearer_token, "bearer_token")
        if api_key:
            reject_control_chars(api_key, "api_key")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Resubscribing to task %s at %s", task_id, resolved_url)

    credentials = resolved_credentials

    async def do_resubscribe() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(
                    http_client, resolved_url, credentials=credentials
                )

                output.dim(f"Resubscribing to task {task_id}...")

                collected_text: list[str] = []
                last_state: str | None = None
                last_task: Task | None = None
                async for event in service.resubscribe(task_id):
                    if event.task:
                        last_task = event.task
                    if event.event_type == "status":
                        last_state = event.state.value if event.state else "unknown"
                        output.state("Status", last_state)
                    elif event.text:
                        output.line(event.text)
                        collected_text.append(event.text)

                if output.is_structured and last_task:
                    output.json(protocol_dump(last_task))

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_resubscribe())


def _format_task(task: Task, output: Output, raw: bool = False) -> None:
    """Format and display a task."""
    if output.is_structured or raw:
        output.json(protocol_dump(task))
        return

    text = extract_text(task)

    output.blank()
    output.field("Task ID", task.id)
    state = response_state(task)
    if state:
        output.state("State", state.value)
    context_id = response_context_id(task)
    if context_id:
        output.field("Context ID", context_id)

    if text:
        output.blank()
        output.markdown(text)


@task.group("notification")
def task_notification() -> None:
    """Manage push notification configurations for tasks."""
    pass


@task_notification.command("set")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", required=True, help="Task ID")
@click.option(
    "--webhook-url", required=True, help="Webhook URL to receive notifications"
)
@click.option("--token", "-t", help="Authentication token for the webhook")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def notification_set(
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: str,
    webhook_url: str,
    token: Optional[str],
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Configure a push notification webhook for a task.

    \b
    Examples:
      $ handler task notification set --server my_agent --task task-123 --webhook-url http://webhook.example.com
      $ handler task notification set --url http://localhost:8000 --task task-123 --webhook-url http://webhook.example.com --token SECRET
    """
    output = Output()

    resolved_url, resolved_credentials = resolve_agent_target(
        agent_url, server_name, bearer_token, api_key
    )

    try:
        validate_agent_url(resolved_url)
        validate_resource_id(task_id, "task_id")
        validate_webhook_url(webhook_url)
        if token:
            reject_control_chars(token, "token")
        if bearer_token:
            reject_control_chars(bearer_token, "bearer_token")
        if api_key:
            reject_control_chars(api_key, "api_key")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Setting push config for task %s at %s", task_id, resolved_url)

    credentials = resolved_credentials

    async def do_set() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(
                    http_client, resolved_url, credentials=credentials
                )

                output.dim(f"Setting notification config for task {task_id}...")

                config = await service.set_push_config(task_id, webhook_url, token)

                if output.is_structured:
                    data: dict[str, object] = {"task_id": config.task_id}
                    if config.push_notification_config:
                        pnc = config.push_notification_config
                        data["url"] = pnc.url
                        if pnc.token:
                            data["token"] = pnc.token
                        if pnc.id:
                            data["config_id"] = pnc.id
                    output.json(data)
                    return

                output.success("Push notification config set")
                output.field("Task ID", config.task_id)
                if config.push_notification_config:
                    pnc = config.push_notification_config
                    output.field("URL", pnc.url)
                    if pnc.token:
                        output.field("Token", f"{pnc.token[:20]}...")
                    if pnc.id:
                        output.field("Config ID", pnc.id)

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_set())


@task_notification.command("get")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", required=True, help="Task ID")
@click.option("--config-id", "-c", help="Specific push notification config ID")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def notification_get(
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: str,
    config_id: Optional[str],
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Get the push notification configuration for a task.

    \b
    Examples:
      $ handler task notification get --server my_agent --task task-123
      $ handler task notification get --url http://localhost:8000 --task task-123
    """
    output = Output()

    resolved_url, resolved_credentials = resolve_agent_target(
        agent_url, server_name, bearer_token, api_key
    )

    try:
        validate_agent_url(resolved_url)
        validate_resource_id(task_id, "task_id")
        if config_id:
            validate_resource_id(config_id, "config_id")
        if bearer_token:
            reject_control_chars(bearer_token, "bearer_token")
        if api_key:
            reject_control_chars(api_key, "api_key")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Getting push config for task %s at %s", task_id, resolved_url)

    credentials = resolved_credentials

    async def do_get() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(
                    http_client, resolved_url, credentials=credentials
                )

                config = await service.get_push_config(task_id, config_id)

                if output.is_structured:
                    data: dict[str, object] = {"task_id": config.task_id}
                    if config.push_notification_config:
                        pnc = config.push_notification_config
                        data["url"] = pnc.url
                        if pnc.token:
                            data["token"] = pnc.token
                        if pnc.id:
                            data["config_id"] = pnc.id
                    output.json(data)
                    return

                output.field("Task ID", config.task_id)
                if config.push_notification_config:
                    pnc = config.push_notification_config
                    output.field("URL", pnc.url)
                    if pnc.token:
                        output.field("Token", f"{pnc.token[:20]}...")
                    if pnc.id:
                        output.field("Config ID", pnc.id)

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_get())
