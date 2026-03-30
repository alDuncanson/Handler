"""Command-line interface for the Handler A2A protocol client.

Provides commands for interacting with A2A agents:
- message send/stream: Send messages to agents
- task get/cancel/resubscribe: Manage tasks
- task notification set: Configure push notifications
- card get/validate: Agent card operations
- server list/show/add/remove/validate: Manage configured servers
- server run agent/push: Run local servers
- session list/show/clear: Manage saved conversation sessions

Authentication is configured per-server via `handler server add` or
supplied ad-hoc with --bearer / --api-key flags.
"""

import truststore

truststore.inject_into_ssl()

import logging

logging.getLogger().setLevel(logging.WARNING)

import click

from a2a_handler import __version__
from a2a_handler.common import Output, configure_output, get_logger, setup_logging
from a2a_handler.common.output import OutputFormat
from a2a_handler.tui import HandlerTUI

from .card import card
from .mcp import mcp
from .message import message
from .schema import describe, schema
from .server import server
from .session import session
from .task import task

log = get_logger(__name__)


@click.group()
@click.version_option(version=__version__, prog_name="handler")
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
cli.add_command(mcp)
cli.add_command(schema)
cli.add_command(describe)


@cli.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Display the current version.

    **Examples:**

    ```
    handler version
    handler --output json version
    ```
    """
    output = Output()
    output_format = (ctx.obj or {}).get("output_format", "text")
    if output_format == "text":
        output.line(__version__)
    else:
        output.json({"version": __version__})


@cli.command()
@click.option("--bearer", "-b", "bearer_token", help="Bearer token for agent auth")
@click.option(
    "--connect",
    "-c",
    "connect_servers",
    multiple=True,
    help="Named server to pre-connect on startup (repeatable)",
)
@click.option("--url", help="URL to pre-connect on startup")
def tui(
    bearer_token: str | None,
    connect_servers: tuple[str, ...],
    url: str | None,
) -> None:
    """Launch the interactive terminal interface.

    **Examples:**

    ```
    handler tui
    handler tui --connect my_agent
    handler tui --connect my_agent --connect other_agent
    handler tui --url http://localhost:8000
    handler tui --bearer TOKEN
    ```
    """
    log.info("Launching TUI")
    logging.getLogger().handlers = []
    app = HandlerTUI(
        initial_bearer_token=bearer_token,
        connect_servers=connect_servers or None,
        connect_url=url,
    )
    app.run()


@cli.command()
@click.option("--host", default="localhost", help="Host to bind to", show_default=True)
@click.option("--port", "-p", default=8001, help="Port to bind to", show_default=True)
def web(host: str, port: int) -> None:
    """Serve the TUI as a web application.

    **Examples:**

    ```
    handler web
    handler web --port 9000
    ```
    """
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
