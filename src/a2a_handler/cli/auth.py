"""Auth commands for managing authentication credentials."""

from typing import Optional

import rich_click as click

from a2a_handler.auth import AuthType, create_api_key_auth, create_bearer_auth
from a2a_handler.common import Output
from a2a_handler.common import (
    clear_agent_bearer_command,
    get_agent_bearer_command,
    get_default_bearer_command,
    save_agent_bearer_command,
    save_default_bearer_command,
)
from a2a_handler.common.input_validation import (
    InputValidationError,
    reject_control_chars,
    validate_agent_url,
)
from a2a_handler.credentials import (
    BUILTIN_BEARER_PROVIDERS,
    get_builtin_provider_command,
)
from a2a_handler.session import clear_credentials, get_credentials, set_credentials

from ._helpers import handle_validation_error


@click.group()
def auth() -> None:
    """Manage authentication credentials for agents."""
    pass


@auth.command("set")
@click.argument("agent_url")
@click.option("--bearer", "-b", "bearer_token", help="Bearer token for authentication")
@click.option("--api-key", "-k", "api_key", help="API key for authentication")
@click.option(
    "--api-key-header",
    default="X-API-Key",
    help="Header name for API key (default: X-API-Key)",
)
def auth_set(
    agent_url: str,
    bearer_token: Optional[str],
    api_key: Optional[str],
    api_key_header: str,
) -> None:
    """Set authentication credentials for an agent.

    Provide either --bearer or --api-key (not both).
    """
    output = Output()
    try:
        validate_agent_url(agent_url)
        reject_control_chars(api_key_header, "api_key_header")
        if bearer_token:
            reject_control_chars(bearer_token, "bearer_token")
        if api_key:
            reject_control_chars(api_key, "api_key")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    if bearer_token and api_key:
        output.error("Provide either --bearer or --api-key, not both")
        raise click.Abort()

    if not bearer_token and not api_key:
        output.error("Provide --bearer or --api-key")
        raise click.Abort()

    if bearer_token:
        credentials = create_bearer_auth(bearer_token)
        auth_type_display = "Bearer token"
    else:
        credentials = create_api_key_auth(api_key or "", header_name=api_key_header)
        auth_type_display = f"API key (header: {api_key_header})"

    set_credentials(agent_url, credentials)

    output.success(f"Set {auth_type_display} for {agent_url} (saved to OS keyring)")


@auth.command("show")
@click.argument("agent_url")
def auth_show(agent_url: str) -> None:
    """Show authentication credentials for an agent."""
    output = Output()
    try:
        validate_agent_url(agent_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    credentials = get_credentials(agent_url)

    output.header(f"Auth for {agent_url}")

    if not credentials:
        output.dim("No credentials configured")
        return

    output.field("Type", credentials.auth_type.value)
    masked_value = (
        f"{credentials.value[:4]}...{credentials.value[-4:]}"
        if len(credentials.value) > 8
        else "****"
    )
    output.field("Value", masked_value)

    if credentials.auth_type == AuthType.API_KEY:
        output.field("Header", credentials.header_name or "X-API-Key")


@auth.command("clear")
@click.argument("agent_url")
def auth_clear(agent_url: str) -> None:
    """Clear authentication credentials for an agent."""
    output = Output()
    try:
        validate_agent_url(agent_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    clear_credentials(agent_url)
    output.success(f"Cleared credentials for {agent_url}")


@auth.group("source")
def auth_source() -> None:
    """Manage automatic bearer token sources."""
    pass


@auth_source.command("set")
@click.argument("agent_url", required=False)
@click.option(
    "--provider",
    type=click.Choice(sorted(BUILTIN_BEARER_PROVIDERS.keys())),
    help="Built-in provider for bearer tokens (for example: gcloud)",
)
@click.option(
    "--command",
    "bearer_command",
    help="Command that prints a bearer token to stdout",
)
def auth_source_set(
    agent_url: str | None,
    provider: str | None,
    bearer_command: str | None,
) -> None:
    """Set an automatic bearer token command for an agent or globally.

    If AGENT_URL is omitted, sets the global default source.
    """
    output = Output()
    try:
        if agent_url:
            validate_agent_url(agent_url)
        if provider and bearer_command:
            raise InputValidationError(
                code="invalid_auth_source_arguments",
                message="Provide either --provider or --command, not both",
                suggestion="Pick one auth source mode",
            )
        if not provider and not bearer_command:
            raise InputValidationError(
                code="missing_auth_source_arguments",
                message="Provide --provider or --command",
                suggestion="For gcloud use: --provider gcloud",
            )
        if bearer_command:
            reject_control_chars(bearer_command, "bearer_command")
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    command = bearer_command
    if provider:
        command = get_builtin_provider_command(provider)
        if command is None:
            output.error(f"Unsupported provider: {provider}")
            raise click.Abort()

    assert command is not None
    if agent_url:
        save_agent_bearer_command(agent_url, command)
        output.success(f"Set auth source for {agent_url}")
    else:
        save_default_bearer_command(command)
        output.success("Set global auth source")

    if provider:
        output.field("Provider", provider)
    output.field("Command", command)


@auth_source.command("show")
@click.argument("agent_url", required=False)
def auth_source_show(agent_url: str | None) -> None:
    """Show configured automatic bearer token sources."""
    output = Output()
    try:
        if agent_url:
            validate_agent_url(agent_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    output.header("Auth Source")

    if agent_url:
        command = get_agent_bearer_command(agent_url)
        if command:
            output.field("Scope", f"Agent: {agent_url}")
            output.field("Command", command)
            return

        default_command = get_default_bearer_command()
        if default_command:
            output.field("Scope", f"Default fallback for {agent_url}")
            output.field("Command", default_command)
            return

        output.dim("No auth source configured")
        return

    command = get_default_bearer_command()
    if command:
        output.field("Scope", "Global")
        output.field("Command", command)
    else:
        output.dim("No global auth source configured")


@auth_source.command("clear")
@click.argument("agent_url", required=False)
def auth_source_clear(agent_url: str | None) -> None:
    """Clear automatic bearer token source for an agent or globally."""
    output = Output()
    try:
        if agent_url:
            validate_agent_url(agent_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    if agent_url:
        clear_agent_bearer_command(agent_url)
        output.success(f"Cleared auth source for {agent_url}")
    else:
        save_default_bearer_command(None)
        output.success("Cleared global auth source")
