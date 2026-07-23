"""Card commands for agent card operations."""

import asyncio
from typing import Any, Optional

import click
from a2a.types import AgentCard

from a2a_handler.auth import AuthType
from a2a_handler.common import Output, get_logger
from a2a_handler.common.input_validation import InputValidationError, validate_agent_url
from a2a_handler.service import A2AService, recommend_auth_from_card, to_json_dict
from a2a_handler.validation import (
    ValidationResult,
    ValidationSource,
    validate_agent_card_from_file,
)

from ._helpers import (
    build_http_client,
    handle_client_error,
    handle_validation_error,
    resolve_agent_selection,
    resolve_selection_credentials,
)

log = get_logger(__name__)


@click.group()
def card() -> None:
    """Agent card operations."""
    pass


@card.command("get")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
@click.option(
    "--google-audience",
    help="Use Google Cloud ID-token auth (ADC); audience defaults to the agent URL",
)
def card_get(
    agent_url: Optional[str],
    server_name: Optional[str],
    bearer_env: Optional[str],
    api_key_env: Optional[str],
    google_audience: Optional[str],
) -> None:
    """Retrieve an agent's card.

    \b
    Examples:
      $ handler card get --server my_agent
      $ handler card get --url http://localhost:8000
      $ handler card get --url http://localhost:8000 --bearer-env MY_TOKEN
      $ handler card get --url https://agent-xxxx-uc.a.run.app --google-audience https://agent-xxxx-uc.a.run.app
    """
    output = Output()

    selection = resolve_agent_selection(agent_url, server_name)
    resolved_url = selection.agent_url

    try:
        validate_agent_url(resolved_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Fetching agent card from %s", resolved_url)

    credentials = resolve_selection_credentials(
        selection, bearer_env, api_key_env, google_audience
    )

    async def do_get() -> None:
        try:
            async with build_http_client(credentials=credentials) as http_client:
                service = A2AService(http_client, resolved_url, credentials=credentials)
                card_data = await service.get_card()
                log.info("Retrieved card for agent: %s", card_data.name)

                _format_agent_card(card_data, output)
                if credentials is None:
                    _hint_card_auth(card_data)

        except Exception as e:
            handle_client_error(e, resolved_url, output)
            raise click.Abort()

    asyncio.run(do_get())


_AUTH_FLAG_HINTS = {
    AuthType.API_KEY: "--api-key-env (or a servers.toml api_key entry)",
    AuthType.BEARER: "--bearer-env",
    AuthType.OAUTH2: "a servers.toml oauth2 entry",
    AuthType.MTLS: "--cert/--key (or a servers.toml mtls entry)",
}


def _hint_card_auth(card: AgentCard) -> None:
    """Print a stderr hint when a card declares auth but none was supplied."""
    recommendation = recommend_auth_from_card(card)
    if recommendation is None:
        return
    flag = _AUTH_FLAG_HINTS.get(recommendation.auth_type, "the appropriate auth flag")
    click.echo(
        f"Note: this agent declares {recommendation.detail}; no credentials were "
        f"supplied. Configure auth with {flag}.",
        err=True,
    )


def _format_agent_card(card_data: object, output: Output) -> None:
    """Format and display an agent card as JSON."""
    card_dict: dict[str, Any]
    if isinstance(card_data, AgentCard):
        card_dict = to_json_dict(card_data)
    elif isinstance(card_data, dict):
        card_dict = {str(key): value for key, value in card_data.items()}
    else:
        card_dict = {}
    output.json(card_dict)


@card.command("validate")
@click.option("--url", "agent_url", help="Agent URL to validate")
@click.option("--file", "file_path", help="File path to validate")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token (overrides saved)"
)
@click.option(
    "--api-key-env", "-k", help="Env var containing API key (overrides saved)"
)
def card_validate(
    agent_url: Optional[str],
    file_path: Optional[str],
    server_name: Optional[str],
    bearer_env: Optional[str],
    api_key_env: Optional[str],
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

    selection = resolve_agent_selection(agent_url, server_name)
    resolved_url = selection.agent_url

    try:
        validate_agent_url(resolved_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    log.info("Validating agent card from %s", resolved_url)

    credentials = resolve_selection_credentials(selection, bearer_env, api_key_env)

    async def do_validate() -> None:
        async with build_http_client(credentials=credentials) as http_client:
            service = A2AService(http_client, resolved_url, credentials=credentials)
            agent_card = await service.get_card()
            result = ValidationResult(
                valid=True,
                source=resolved_url,
                source_type=ValidationSource.URL,
                agent_card=agent_card,
            )

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
