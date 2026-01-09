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

logging.getLogger().setLevel(logging.WARNING)

import rich_click as click

from a2a_handler import __version__
from a2a_handler.common import get_logger, setup_logging
from a2a_handler.tui import HandlerTUI

from . import _config  # noqa: F401 - configures rich-click on import
from .auth import auth
from .card import card
from .mcp import mcp
from .message import message
from .server import server
from .session import session
from .task import task

log = get_logger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--debug", "-d", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, debug: bool) -> None:
    """Handler - A2A protocol client CLI."""
    ctx.ensure_object(dict)

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


@cli.command()
def version() -> None:
    """Display the current version."""
    click.echo(__version__)


@cli.command()
def tui() -> None:
    """Launch the interactive terminal interface."""
    log.info("Launching TUI")
    logging.getLogger().handlers = []
    app = HandlerTUI()
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
