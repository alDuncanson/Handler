"""Card commands for agent card operations."""

import asyncio
import json
from typing import Any

import rich_click as click
from a2a.types import AgentCard

from a2a_handler.common import Output, get_logger
from a2a_handler.service import A2AService
from a2a_handler.session import get_credentials
from a2a_handler.validation import (
    ValidationResult,
    validate_agent_card_from_file,
    validate_agent_card_from_url,
)

from ._helpers import build_http_client, handle_client_error

log = get_logger(__name__)


@click.group()
def card() -> None:
    """Agent card operations."""
    pass


@card.command("get")
@click.argument("agent_url")
@click.option(
    "--authenticated", "-a", is_flag=True, help="Request authenticated extended card"
)
def card_get(agent_url: str, authenticated: bool) -> None:
    """Retrieve an agent's card."""
    log.info("Fetching agent card from %s", agent_url)
    credentials = get_credentials(agent_url) if authenticated else None
    if authenticated and credentials is None:
        log.warning("No saved credentials found for %s", agent_url)

    async def do_get() -> None:
        output = Output()
        try:
            async with build_http_client() as http_client:
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
    else:
        card_dict = {}
    output.line(json.dumps(card_dict, indent=2))


@card.command("validate")
@click.argument("source")
def card_validate(source: str) -> None:
    """Validate an agent card from URL or file."""
    log.info("Validating agent card from %s", source)
    is_url = source.startswith(("http://", "https://"))

    async def do_validate() -> None:
        output = Output()
        if is_url:
            async with build_http_client() as http_client:
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
