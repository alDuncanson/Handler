"""Task commands for managing A2A tasks."""

import asyncio
from typing import Any
from typing import Optional

import click

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
    protocol_dump,
    push_config_dump,
)

from ._helpers import (
    build_http_client,
    build_streaming_http_client,
    handle_client_error,
    handle_validation_error,
    require_task_id,
    resolve_agent_selection,
    resolve_selection_credentials,
    resolve_task_id,
)

log = get_logger(__name__)


@click.group()
def task() -> None:
    """Manage A2A tasks."""
    pass


@task.command("get")
@click.argument("task_id_arg", metavar="[TASK_ID]", required=False)
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", help="Task ID to retrieve (alias for TASK_ID)")
@click.option(
    "--history-length", "-n", type=int, help="Number of history messages to include"
)
@click.option(
    "--params",
    "json_params",
    help="Raw JSON params object for agent-friendly invocation",
)
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
def task_get(
    task_id_arg: Optional[str],
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: Optional[str],
    history_length: Optional[int],
    json_params: Optional[str],
    bearer_env: Optional[str],
    api_key_env: Optional[str],
) -> None:
    """Retrieve the current status of a task.

    \b
    Examples:
      $ handler task get task-123 --server my_agent
      $ handler task get --server my_agent --task task-123
      $ handler task get --url http://localhost:8000 --task task-123
      $ handler task get task-123 --server my_agent --history-length 10
    """
    output = Output()
    payload: dict[str, Any] = {}
    task_id = resolve_task_id(task_id_arg, task_id)

    selection = resolve_agent_selection(agent_url, server_name)
    resolved_url = selection.agent_url

    try:
        validate_agent_url(resolved_url)
        if json_params:
            payload = parse_json_object(json_params, "params")
            reject_unknown_keys(
                payload,
                {"task_id", "history_length"},
                "params",
            )
        payload_task_id = payload.get("task_id")
        if isinstance(payload_task_id, str):
            task_id = payload_task_id

        payload_history_length = payload.get("history_length")
        if history_length is None and isinstance(payload_history_length, int):
            history_length = payload_history_length

        task_id = require_task_id(task_id)
        validate_resource_id(task_id, "task_id")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Getting task %s from %s", task_id, resolved_url)

    credentials = resolve_selection_credentials(selection, bearer_env, api_key_env)

    async def do_get() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(http_client, resolved_url, credentials=credentials)
                task = await service.get_task(task_id, history_length)
                _format_task(task, output)
        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_get())


@task.command("cancel")
@click.argument("task_id_arg", metavar="[TASK_ID]", required=False)
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", help="Task ID to cancel (alias for TASK_ID)")
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
def task_cancel(
    task_id_arg: Optional[str],
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: Optional[str],
    bearer_env: Optional[str],
    api_key_env: Optional[str],
) -> None:
    """Request cancellation of a task.

    \b
    Examples:
      $ handler task cancel task-123 --server my_agent
      $ handler task cancel --server my_agent --task task-123
      $ handler task cancel --url http://localhost:8000 --task task-123
    """
    output = Output()
    task_id = require_task_id(resolve_task_id(task_id_arg, task_id))

    selection = resolve_agent_selection(agent_url, server_name)
    resolved_url = selection.agent_url

    try:
        validate_agent_url(resolved_url)
        validate_resource_id(task_id, "task_id")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Canceling task %s at %s", task_id, resolved_url)

    credentials = resolve_selection_credentials(selection, bearer_env, api_key_env)

    async def do_cancel() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(http_client, resolved_url, credentials=credentials)

                task = await service.cancel_task(task_id)
                _format_task(task, output)

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_cancel())


@task.command("resubscribe")
@click.argument("task_id_arg", metavar="[TASK_ID]", required=False)
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", help="Task ID to resubscribe to (alias for TASK_ID)")
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
def task_resubscribe(
    task_id_arg: Optional[str],
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: Optional[str],
    bearer_env: Optional[str],
    api_key_env: Optional[str],
) -> None:
    """Resubscribe to a task's SSE stream after disconnection.

    \b
    Examples:
      $ handler task resubscribe task-123 --server my_agent
      $ handler task resubscribe --server my_agent --task task-123
      $ handler task resubscribe --url http://localhost:8000 --task task-123
    """
    output = Output()
    task_id = require_task_id(resolve_task_id(task_id_arg, task_id))

    selection = resolve_agent_selection(agent_url, server_name)
    resolved_url = selection.agent_url

    try:
        validate_agent_url(resolved_url)
        validate_resource_id(task_id, "task_id")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Resubscribing to task %s at %s", task_id, resolved_url)

    credentials = resolve_selection_credentials(selection, bearer_env, api_key_env)

    async def do_resubscribe() -> None:
        try:
            async with build_streaming_http_client(
                credentials=credentials
            ) as http_client:
                service = A2AService(http_client, resolved_url, credentials=credentials)

                last_task: Task | None = None
                async for event in service.resubscribe(task_id):
                    if event.task:
                        last_task = event.task

                if last_task:
                    output.json(protocol_dump(last_task))
                else:
                    output.error(
                        code="no_response",
                        message="No task received from resubscription",
                    )

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_resubscribe())


def _format_task(task: Task, output: Output) -> None:
    """Format and display a task."""
    output.json(protocol_dump(task))


@task.group("notification")
def task_notification() -> None:
    """Manage push notification configurations for tasks."""
    pass


@task_notification.command("set")
@click.argument("task_id_arg", metavar="[TASK_ID]", required=False)
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", help="Task ID (alias for TASK_ID)")
@click.option(
    "--webhook-url", required=True, help="Webhook URL to receive notifications"
)
@click.option("--token", "-t", help="Authentication token for the webhook")
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
def notification_set(
    task_id_arg: Optional[str],
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: Optional[str],
    webhook_url: str,
    token: Optional[str],
    bearer_env: Optional[str],
    api_key_env: Optional[str],
) -> None:
    """Configure a push notification webhook for a task.

    \b
    Examples:
      $ handler task notification set task-123 --server my_agent --webhook-url http://webhook.example.com
      $ handler task notification set --server my_agent --task task-123 --webhook-url http://webhook.example.com
      $ handler task notification set --url http://localhost:8000 --task task-123 --webhook-url http://webhook.example.com --token SECRET
    """
    output = Output()
    task_id = require_task_id(resolve_task_id(task_id_arg, task_id))

    selection = resolve_agent_selection(agent_url, server_name)
    resolved_url = selection.agent_url

    try:
        validate_agent_url(resolved_url)
        validate_resource_id(task_id, "task_id")
        validate_webhook_url(webhook_url)
        if token:
            reject_control_chars(token, "token")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Setting push config for task %s at %s", task_id, resolved_url)

    credentials = resolve_selection_credentials(selection, bearer_env, api_key_env)

    async def do_set() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(http_client, resolved_url, credentials=credentials)

                config = await service.set_push_config(task_id, webhook_url, token)
                output.json(push_config_dump(config))

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_set())


@task_notification.command("list")
@click.argument("task_id_arg", metavar="[TASK_ID]", required=False)
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", help="Task ID (alias for TASK_ID)")
@click.option(
    "--page-size",
    type=int,
    help="Configs per request page (all pages are still fetched)",
)
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
def notification_list(
    task_id_arg: Optional[str],
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: Optional[str],
    page_size: Optional[int],
    bearer_env: Optional[str],
    api_key_env: Optional[str],
) -> None:
    """List a task's push notification configs, following pagination to the end.

    \b
    Examples:
      $ handler task notification list task-123 --server my_agent
      $ handler task notification list --server my_agent --task task-123
      $ handler --output json task notification list task-123 --url http://localhost:8000
    """
    output = Output()
    task_id = require_task_id(resolve_task_id(task_id_arg, task_id))

    selection = resolve_agent_selection(agent_url, server_name)
    resolved_url = selection.agent_url

    try:
        validate_agent_url(resolved_url)
        validate_resource_id(task_id, "task_id")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Listing push configs for task %s at %s", task_id, resolved_url)

    credentials = resolve_selection_credentials(selection, bearer_env, api_key_env)

    async def do_list() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(http_client, resolved_url, credentials=credentials)

                configs = await service.list_all_push_configs(
                    task_id, page_size=page_size
                )
                output.json(
                    {
                        "count": len(configs),
                        "configs": [push_config_dump(config) for config in configs],
                    }
                )

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_list())


@task_notification.command("remove")
@click.argument("task_id_arg", metavar="[TASK_ID]", required=False)
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", help="Task ID (alias for TASK_ID)")
@click.option(
    "--config-id", "-c", required=True, help="Push notification config ID to remove"
)
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
def notification_remove(
    task_id_arg: Optional[str],
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: Optional[str],
    config_id: str,
    bearer_env: Optional[str],
    api_key_env: Optional[str],
) -> None:
    """Remove a push notification config from a task.

    \b
    Examples:
      $ handler task notification remove task-123 --server my_agent --config-id cfg-1
      $ handler task notification remove --url http://localhost:8000 --task task-123 --config-id cfg-1
    """
    output = Output()
    task_id = require_task_id(resolve_task_id(task_id_arg, task_id))

    selection = resolve_agent_selection(agent_url, server_name)
    resolved_url = selection.agent_url

    try:
        validate_agent_url(resolved_url)
        validate_resource_id(task_id, "task_id")
        validate_resource_id(config_id, "config_id")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info(
        "Removing push config %s for task %s at %s", config_id, task_id, resolved_url
    )

    credentials = resolve_selection_credentials(selection, bearer_env, api_key_env)

    async def do_remove() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(http_client, resolved_url, credentials=credentials)

                await service.delete_push_config(task_id, config_id)
                if output.is_structured:
                    output.json(
                        {"deleted": True, "task_id": task_id, "config_id": config_id}
                    )
                else:
                    output.text(f"Removed push config {config_id} from {task_id}.")

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_remove())


@task_notification.command("get")
@click.argument("task_id_arg", metavar="[TASK_ID]", required=False)
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--task", "task_id", help="Task ID (alias for TASK_ID)")
@click.option("--config-id", "-c", help="Specific push notification config ID")
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
def notification_get(
    task_id_arg: Optional[str],
    agent_url: Optional[str],
    server_name: Optional[str],
    task_id: Optional[str],
    config_id: Optional[str],
    bearer_env: Optional[str],
    api_key_env: Optional[str],
) -> None:
    """Get the push notification configuration for a task.

    \b
    Examples:
      $ handler task notification get task-123 --server my_agent
      $ handler task notification get --server my_agent --task task-123
      $ handler task notification get --url http://localhost:8000 --task task-123
    """
    output = Output()
    task_id = require_task_id(resolve_task_id(task_id_arg, task_id))

    selection = resolve_agent_selection(agent_url, server_name)
    resolved_url = selection.agent_url

    try:
        validate_agent_url(resolved_url)
        validate_resource_id(task_id, "task_id")
        if config_id:
            validate_resource_id(config_id, "config_id")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Getting push config for task %s at %s", task_id, resolved_url)

    credentials = resolve_selection_credentials(selection, bearer_env, api_key_env)

    async def do_get() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(http_client, resolved_url, credentials=credentials)

                config = await service.get_push_config(task_id, config_id)
                output.json(push_config_dump(config))

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_get())
