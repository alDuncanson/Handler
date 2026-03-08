"""Task commands for managing A2A tasks."""

import asyncio
from typing import Any
from typing import Optional

import rich_click as click

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
from a2a_handler.service import A2AService, TaskResult
from a2a_handler.session import get_credentials

from ._helpers import (
    build_http_client,
    handle_client_error,
    handle_validation_error,
)

log = get_logger(__name__)


@click.group()
def task() -> None:
    """Manage A2A tasks."""
    pass


@task.command("get")
@click.argument("agent_url")
@click.argument("task_id")
@click.option(
    "--history-length", "-n", type=int, help="Number of history messages to include"
)
@click.option(
    "--params",
    "json_params",
    help="Raw JSON params object for agent-friendly invocation",
)
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def task_get(
    agent_url: str,
    task_id: str,
    history_length: Optional[int],
    json_params: Optional[str],
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Retrieve the current status of a task."""
    output = Output()
    payload: dict[str, Any] = {}
    try:
        validate_agent_url(agent_url)
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

    log.info("Getting task %s from %s", task_id, agent_url)

    credentials: AuthCredentials | None = None
    if bearer_token:
        credentials = create_bearer_auth(bearer_token)
    elif api_key:
        credentials = create_api_key_auth(api_key)
    else:
        credentials = get_credentials(agent_url)

    async def do_get() -> None:
        try:
            async with build_http_client() as http_client:
                service = A2AService(http_client, agent_url, credentials=credentials)
                result = await service.get_task(task_id, history_length)
                _format_task_result(result, output)
        except Exception as e:
            handle_client_error(e, agent_url, output)
            raise click.Abort()

    asyncio.run(do_get())


@task.command("cancel")
@click.argument("agent_url")
@click.argument("task_id")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def task_cancel(
    agent_url: str,
    task_id: str,
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Request cancellation of a task."""
    output = Output()
    try:
        validate_agent_url(agent_url)
        validate_resource_id(task_id, "task_id")
        if bearer_token:
            reject_control_chars(bearer_token, "bearer_token")
        if api_key:
            reject_control_chars(api_key, "api_key")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Canceling task %s at %s", task_id, agent_url)

    credentials: AuthCredentials | None = None
    if bearer_token:
        credentials = create_bearer_auth(bearer_token)
    elif api_key:
        credentials = create_api_key_auth(api_key)
    else:
        credentials = get_credentials(agent_url)

    async def do_cancel() -> None:
        try:
            async with build_http_client() as http_client:
                service = A2AService(http_client, agent_url, credentials=credentials)

                output.dim(f"Canceling task {task_id}...")

                result = await service.cancel_task(task_id)
                _format_task_result(result, output)

                output.success("Task canceled")

        except Exception as e:
            handle_client_error(e, agent_url, output)
            raise click.Abort()

    asyncio.run(do_cancel())


@task.command("resubscribe")
@click.argument("agent_url")
@click.argument("task_id")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def task_resubscribe(
    agent_url: str,
    task_id: str,
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Resubscribe to a task's SSE stream after disconnection."""
    output = Output()
    try:
        validate_agent_url(agent_url)
        validate_resource_id(task_id, "task_id")
        if bearer_token:
            reject_control_chars(bearer_token, "bearer_token")
        if api_key:
            reject_control_chars(api_key, "api_key")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Resubscribing to task %s at %s", task_id, agent_url)

    credentials: AuthCredentials | None = None
    if bearer_token:
        credentials = create_bearer_auth(bearer_token)
    elif api_key:
        credentials = create_api_key_auth(api_key)
    else:
        credentials = get_credentials(agent_url)

    async def do_resubscribe() -> None:
        try:
            async with build_http_client() as http_client:
                service = A2AService(http_client, agent_url, credentials=credentials)

                output.dim(f"Resubscribing to task {task_id}...")

                async for event in service.resubscribe(task_id):
                    if event.event_type == "status":
                        output.state(
                            "Status",
                            event.state.value if event.state else "unknown",
                        )
                    elif event.text:
                        output.line(event.text)

        except Exception as e:
            handle_client_error(e, agent_url, output)
            raise click.Abort()

    asyncio.run(do_resubscribe())


def _format_task_result(result: TaskResult, output: Output) -> None:
    """Format and display a task result."""
    output.blank()
    output.field("Task ID", result.task_id, dim_value=True)
    output.state("State", result.state.value)
    if result.context_id:
        output.field("Context ID", result.context_id, dim_value=True)

    if result.text:
        output.blank()
        output.markdown(result.text)


@task.group("notification")
def task_notification() -> None:
    """Manage push notification configurations for tasks."""
    pass


@task_notification.command("set")
@click.argument("agent_url")
@click.argument("task_id")
@click.option("--url", "-u", required=True, help="Webhook URL to receive notifications")
@click.option("--token", "-t", help="Authentication token for the webhook")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def notification_set(
    agent_url: str,
    task_id: str,
    url: str,
    token: Optional[str],
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Configure a push notification webhook for a task."""
    output = Output()
    try:
        validate_agent_url(agent_url)
        validate_resource_id(task_id, "task_id")
        validate_webhook_url(url)
        if token:
            reject_control_chars(token, "token")
        if bearer_token:
            reject_control_chars(bearer_token, "bearer_token")
        if api_key:
            reject_control_chars(api_key, "api_key")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Setting push config for task %s at %s", task_id, agent_url)

    credentials: AuthCredentials | None = None
    if bearer_token:
        credentials = create_bearer_auth(bearer_token)
    elif api_key:
        credentials = create_api_key_auth(api_key)
    else:
        credentials = get_credentials(agent_url)

    async def do_set() -> None:
        try:
            async with build_http_client() as http_client:
                service = A2AService(http_client, agent_url, credentials=credentials)

                output.dim(f"Setting notification config for task {task_id}...")

                config = await service.set_push_config(task_id, url, token)

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
            handle_client_error(e, agent_url, output)
            raise click.Abort()

    asyncio.run(do_set())


@task_notification.command("get")
@click.argument("agent_url")
@click.argument("task_id")
@click.option("--config-id", "-c", help="Specific push notification config ID")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def notification_get(
    agent_url: str,
    task_id: str,
    config_id: Optional[str],
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Get the push notification configuration for a task."""
    output = Output()
    try:
        validate_agent_url(agent_url)
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

    log.info("Getting push config for task %s at %s", task_id, agent_url)

    credentials: AuthCredentials | None = None
    if bearer_token:
        credentials = create_bearer_auth(bearer_token)
    elif api_key:
        credentials = create_api_key_auth(api_key)
    else:
        credentials = get_credentials(agent_url)

    async def do_get() -> None:
        try:
            async with build_http_client() as http_client:
                service = A2AService(http_client, agent_url, credentials=credentials)

                config = await service.get_push_config(task_id, config_id)

                output.field("Task ID", config.task_id)
                if config.push_notification_config:
                    pnc = config.push_notification_config
                    output.field("URL", pnc.url)
                    if pnc.token:
                        output.field("Token", f"{pnc.token[:20]}...")
                    if pnc.id:
                        output.field("Config ID", pnc.id)

        except Exception as e:
            handle_client_error(e, agent_url, output)
            raise click.Abort()

    asyncio.run(do_get())
