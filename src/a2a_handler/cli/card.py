"""Card commands for agent card operations."""

import asyncio
from typing import Any

import rich_click as click
from a2a.types import AgentCard

from a2a_handler.common import Output, get_logger
from a2a_handler.common.input_validation import InputValidationError, validate_agent_url
from a2a_handler.service import A2AService
from a2a_handler.session import get_credentials
from a2a_handler.validation import (
    ValidationResult,
    validate_agent_card_from_file,
    validate_agent_card_from_url,
)

from ._helpers import (
    build_http_client,
    handle_client_error,
    handle_validation_error,
)

log = get_logger(__name__)


@click.group()
def card() -> None:
    """Agent card operations."""
    pass


@card.command("get")
@click.argument("agent_url")
def card_get(agent_url: str) -> None:
    """Retrieve an agent's card."""
    output = Output()
    try:
        validate_agent_url(agent_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Fetching agent card from %s", agent_url)
    credentials = get_credentials(agent_url)

    async def do_get() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(http_client, agent_url, credentials=credentials)
                card_data = await service.get_card()
                log.info("Retrieved card for agent: %s", card_data.name)

                _format_agent_card(card_data, output)

        except Exception as e:
            handle_client_error(e, agent_url, output)
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
@click.argument("source")
def card_validate(source: str) -> None:
    """Validate an agent card from URL or file."""
    output = Output()
    log.info("Validating agent card from %s", source)
    is_url = source.startswith(("http://", "https://"))
    if is_url:
        try:
            validate_agent_url(source)
        except InputValidationError as error:
            handle_validation_error(error, output)
            raise click.Abort() from error

    credentials = get_credentials(source) if is_url else None

    async def do_validate() -> None:
        if is_url:
            async with build_http_client(credentials=credentials) as http_client:
                result = await validate_agent_card_from_url(source, http_client)
        else:
            result = validate_agent_card_from_file(source)

        _format_validation_result(result, output)

        if not result.valid:
            raise SystemExit(1)

    asyncio.run(do_validate())


def _format_validation_result(result: ValidationResult, output: Output) -> None:
    """Format and display validation result."""
    if result.valid:
        output.success("Valid Agent Card")
        output.field("Agent", result.agent_name)
        output.field("Protocol Version", result.protocol_version)
        output.field("Source", result.source)
    else:
        output.error("Invalid Agent Card")
        output.field("Source", result.source)
        output.blank()
        output.line(f"Errors ({len(result.issues)}):")
        for issue in result.issues:
            output.list_item(f"{issue.field_name}: {issue.message}", bullet="✗")
