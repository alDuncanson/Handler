"""Command-line interface for the Handler A2A protocol client.

Provides commands for interacting with A2A agents:
- message send/stream: Send messages to agents
- task get/cancel/resubscribe: Manage tasks
- task notification set: Configure push notifications
- card get/validate: Agent card operations
- server agent/push: Run local servers
- session list/show/clear: Manage saved sessions
"""

import truststore

truststore.inject_into_ssl()

import logging
import shlex
import subprocess

logging.getLogger().setLevel(logging.WARNING)

import rich_click as click

from a2a_handler import __version__
from a2a_handler.common import Output, configure_output, get_logger, setup_logging
from a2a_handler.common.input_validation import reject_control_chars
from a2a_handler.common.output import OutputFormat
from a2a_handler.tui import HandlerTUI

from . import _config  # noqa: F401 - configures rich-click on import
from .auth import auth
from .card import card
from .mcp import mcp
from .message import message
from .schema import describe, schema
from .server import server
from .session import session
from .task import task

log = get_logger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--debug", "-d", is_flag=True, help="Enable debug logging")
@click.option(
    "--output",
    "output_format",
    type=click.Choice(["text", "json", "ndjson"]),
    default="text",
    show_default=True,
    help="Output format for command results",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Suppress non-error output",
)
@click.pass_context
def cli(
    ctx: click.Context,
    verbose: bool,
    debug: bool,
    output_format: OutputFormat,
    quiet: bool,
) -> None:
    """Handler - A2A protocol client CLI."""
    ctx.ensure_object(dict)
    ctx.obj["output_format"] = output_format
    ctx.obj["quiet"] = quiet
    configure_output(output_format=output_format, quiet=quiet)

    if debug:
        setup_logging(level="DEBUG")
    elif verbose:
        setup_logging(level="INFO")
    else:
        setup_logging(level="ERROR")


cli.add_command(message)
cli.add_command(task)
cli.add_command(card)
cli.add_command(server)
cli.add_command(session)
cli.add_command(auth)
cli.add_command(mcp)
cli.add_command(schema)
cli.add_command(describe)


@cli.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Display the current version."""
    output = Output()
    output_format = (ctx.obj or {}).get("output_format", "text")
    if output_format == "text":
        output.line(__version__)
    else:
        output.json({"version": __version__})


@cli.command()
@click.option(
    "--bearer",
    "-b",
    "bearer_token",
    help="Temporary bearer token for this TUI run (not saved)",
)
@click.option(
    "--bearer-command",
    help="Command that prints a temporary bearer token to stdout",
)
@click.option(
    "--bearer-stdin",
    is_flag=True,
    help="Read a temporary bearer token from stdin",
)
def tui(
    bearer_token: str | None,
    bearer_command: str | None,
    bearer_stdin: bool,
) -> None:
    """Launch the interactive terminal interface."""
    auth_sources = [
        bool(bearer_token),
        bool(bearer_command),
        bearer_stdin,
    ]
    if sum(auth_sources) > 1:
        raise click.ClickException(
            "Use only one of --bearer, --bearer-command, or --bearer-stdin"
        )

    resolved_bearer_token = bearer_token
    if bearer_command:
        reject_control_chars(bearer_command, "bearer_command")
        try:
            command_parts = shlex.split(bearer_command)
            if not command_parts:
                raise click.ClickException("--bearer-command cannot be empty")
            command_result = subprocess.run(
                command_parts,
                check=True,
                capture_output=True,
                text=True,
            )
        except ValueError as error:
            raise click.ClickException(f"Invalid --bearer-command: {error}") from error
        except subprocess.CalledProcessError as error:
            stderr = error.stderr.strip() if error.stderr else ""
            message = f"--bearer-command failed with exit code {error.returncode}"
            if stderr:
                message = f"{message}: {stderr}"
            raise click.ClickException(message) from error

        resolved_bearer_token = command_result.stdout.strip()
        if not resolved_bearer_token:
            raise click.ClickException("--bearer-command produced an empty token")

    elif bearer_stdin:
        resolved_bearer_token = click.get_text_stream("stdin").read().strip()
        if not resolved_bearer_token:
            raise click.ClickException("--bearer-stdin received an empty token")

    if resolved_bearer_token:
        reject_control_chars(resolved_bearer_token, "bearer_token")

    log.info("Launching TUI")
    logging.getLogger().handlers = []
    app = HandlerTUI(initial_bearer_token=resolved_bearer_token)
    app.run()


@cli.command()
@click.option("--host", default="localhost", help="Host to bind to", show_default=True)
@click.option("--port", "-p", default=8001, help="Port to bind to", show_default=True)
def web(host: str, port: int) -> None:
    """Serve the TUI as a web application."""
    from textual_serve.server import Server

    log.info("Starting web server on %s:%d", host, port)
    server = Server(
        command="handler tui",
        host=host,
        port=port,
        title="Handler",
    )
    server.serve()


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
