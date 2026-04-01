"""Card commands for agent card operations."""

import asyncio
from typing import Any, Optional

import click
from a2a.types import AgentCard

from a2a_handler.common import Output, get_logger
from a2a_handler.common.input_validation import InputValidationError, validate_agent_url
from a2a_handler.service import A2AService
from a2a_handler.validation import (
    ValidationResult,
    validate_agent_card_from_file,
    validate_agent_card_from_url,
)

from ._helpers import (
    build_http_client,
    handle_client_error,
    handle_validation_error,
    resolve_agent_target,
)

log = get_logger(__name__)


@click.group()
def card() -> None:
    """Agent card operations."""
    pass


@card.command("get")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def card_get(
    agent_url: Optional[str],
    server_name: Optional[str],
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Retrieve an agent's card.

    \b
    Examples:
      $ handler card get --server my_agent
      $ handler card get --url http://localhost:8000
      $ handler card get --url http://localhost:8000 --bearer TOKEN
    """
    output = Output()

    resolved_url, resolved_credentials = resolve_agent_target(
        agent_url, server_name, bearer_token, api_key
    )

    try:
        validate_agent_url(resolved_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Fetching agent card from %s", resolved_url)

    credentials = resolved_credentials

    async def do_get() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(http_client, resolved_url, credentials=credentials)
                card_data = await service.get_card()
                log.info("Retrieved card for agent: %s", card_data.name)

                _format_agent_card(card_data, output)

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_get())


def _format_agent_card(card_data: object, output: Output) -> None:
    """Format and display an agent card as JSON."""
    card_dict: dict[str, Any]
    if isinstance(card_data, AgentCard):
        card_dict = card_data.model_dump(exclude_none=True)
    elif isinstance(card_data, dict):
        card_dict = {str(key): value for key, value in card_data.items()}
    else:
        card_dict = {}
    output.json(card_dict)


@card.command("validate")
@click.option("--url", "agent_url", help="Agent URL to validate")
@click.option("--file", "file_path", help="File path to validate")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token (overrides saved)")
@click.option("--api-key", "-k", help="API key (overrides saved)")
def card_validate(
    agent_url: Optional[str],
    file_path: Optional[str],
    server_name: Optional[str],
    bearer_token: Optional[str],
    api_key: Optional[str],
) -> None:
    """Validate an agent card from URL or file.

    \b
    Examples:
      $ handler card validate --server my_agent
      $ handler card validate --url http://localhost:8000
      $ handler card validate --file ./agent-card.json
    """
    output = Output()

    if file_path and (agent_url or server_name):
        raise click.UsageError("Provide --file or --url/--server, not both.")

    if file_path:
        log.info("Validating agent card from %s", file_path)

        async def do_validate_file() -> None:
            result = validate_agent_card_from_file(file_path)
            _format_validation_result(result, output)
            if not result.valid:
                raise SystemExit(1)

        asyncio.run(do_validate_file())
        return

    resolved_url, resolved_credentials = resolve_agent_target(
        agent_url, server_name, bearer_token, api_key
    )

    try:
        validate_agent_url(resolved_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Validating agent card from %s", resolved_url)

    credentials = resolved_credentials

    async def do_validate() -> None:
        async with build_http_client(credentials=credentials) as http_client:
            result = await validate_agent_card_from_url(resolved_url, http_client)

        _format_validation_result(result, output)

        if not result.valid:
            raise SystemExit(1)

    asyncio.run(do_validate())


def _format_validation_result(result: ValidationResult, output: Output) -> None:
    """Format and display validation result."""
    data: dict[str, object] = {
        "valid": result.valid,
        "source": result.source,
    }
    if result.agent_name:
        data["agent_name"] = result.agent_name
    if result.protocol_version:
        data["protocol_version"] = result.protocol_version
    if result.issues:
        data["issues"] = [
            {"field": issue.field_name, "message": issue.message}
            for issue in result.issues
        ]
    output.json(data)
