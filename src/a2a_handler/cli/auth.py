"""Auth commands for managing authentication credentials."""

from typing import Optional

import rich_click as click

from a2a_handler.auth import (
    AuthType,
    create_api_key_auth,
    create_bearer_auth,
    create_mtls_auth,
    parse_header_string,
)
from a2a_handler.common import Output
from a2a_handler.common.input_validation import (
    InputValidationError,
    reject_control_chars,
    validate_agent_url,
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
@click.option("--cert", "cert_path", help="Client certificate path for mTLS (PEM)")
@click.option("--key", "key_path", help="Client private key path for mTLS (PEM)")
@click.option(
    "--ca-cert",
    "ca_cert_path",
    help="CA certificate path for mTLS server verification (PEM)",
)
@click.option(
    "--header",
    "-H",
    "headers",
    multiple=True,
    help="Custom header (repeatable, format: 'Name: Value')",
)
def auth_set(
    agent_url: str,
    bearer_token: Optional[str],
    api_key: Optional[str],
    api_key_header: str,
    cert_path: Optional[str],
    key_path: Optional[str],
    ca_cert_path: Optional[str],
    headers: tuple[str, ...],
) -> None:
    """Set authentication credentials for an agent.

    Provide --bearer, --api-key, or --cert/--key for mTLS. Custom headers
    can be added to any auth method with --header/-H.
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
                output.error(str(e))
                raise click.Abort() from e

    has_mtls = cert_path or key_path
    method_count = sum(bool(x) for x in [bearer_token, api_key, has_mtls])

    if method_count > 1:
        output.error(
            "Provide only one auth method: --bearer, --api-key, or --cert/--key"
        )
        raise click.Abort()

    if method_count == 0 and not custom_headers:
        output.error("Provide --bearer, --api-key, --cert/--key, or --header")
        raise click.Abort()

    if has_mtls:
        if not cert_path or not key_path:
            output.error("mTLS requires both --cert and --key")
            raise click.Abort()
        try:
            credentials = create_mtls_auth(cert_path, key_path, ca_cert_path)
        except FileNotFoundError as e:
            output.error(str(e))
            raise click.Abort() from e
        auth_type_display = "mTLS client certificate"
    elif bearer_token:
        credentials = create_bearer_auth(bearer_token)
        auth_type_display = "Bearer token"
    elif api_key:
        credentials = create_api_key_auth(api_key, header_name=api_key_header)
        auth_type_display = f"API key (header: {api_key_header})"
    else:
        from a2a_handler.auth import AuthCredentials

        credentials = AuthCredentials(auth_type=AuthType.BEARER)
        auth_type_display = "Custom headers only"

    credentials.custom_headers = custom_headers

    set_credentials(agent_url, credentials)

    parts = [auth_type_display]
    if custom_headers:
        header_names = ", ".join(custom_headers.keys())
        parts.append(f"+ headers: {header_names}")
    output.success(f"Set {' '.join(parts)} for {agent_url}")


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

    if credentials.auth_type == AuthType.MTLS:
        output.field("Certificate", credentials.cert_path or "")
        output.field("Private Key", credentials.key_path or "")
        if credentials.ca_cert_path:
            output.field("CA Certificate", credentials.ca_cert_path)
    else:
        masked_value = (
            f"{credentials.value[:4]}...{credentials.value[-4:]}"
            if len(credentials.value) > 8
            else "****"
        )
        output.field("Value", masked_value)

        if credentials.auth_type == AuthType.API_KEY:
            output.field("Header", credentials.header_name or "X-API-Key")

    if credentials.custom_headers:
        for name, value in credentials.custom_headers.items():
            output.field(f"Header: {name}", value)


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
