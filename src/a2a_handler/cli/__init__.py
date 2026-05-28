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
supplied ad-hoc with --bearer-env / --api-key-env flags.
"""

import truststore

truststore.inject_into_ssl()

import logging
import os
import shutil
import subprocess
import webbrowser
from collections.abc import Sequence
from typing import Any

logging.getLogger().setLevel(logging.WARNING)

import click

from a2a_handler import __version__
from a2a_handler.common import Output, configure_output, get_logger, setup_logging
from a2a_handler.common.dotenv import load_runtime_dotenv
from a2a_handler.common.output import OutputFormat
from a2a_handler.tui import HandlerTUI

from ._helpers import configure_http_timeouts
from .card import card
from .mcp import mcp
from .message import message
from .schema import describe, schema
from .server import server
from .session import session
from .task import task

log = get_logger(__name__)

DOCS_URL = "https://handler.alduncanson.com/"
PACKAGE_NAME = "a2a-handler"


class RuntimeDotenvGroup(click.Group):
    """Click group that loads workspace .env before option envvars resolve."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        """Load runtime dotenv before Click parses envvar-backed options."""
        load_runtime_dotenv()
        return super().main(
            args=args,
            prog_name=prog_name,
            complete_var=complete_var,
            standalone_mode=standalone_mode,
            windows_expand_args=windows_expand_args,
            **extra,
        )


@click.group(cls=RuntimeDotenvGroup)
@click.version_option(version=__version__, prog_name="handler")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--debug", "-d", is_flag=True, help="Enable debug logging")
@click.option(
    "--output",
    "output_format",
    type=click.Choice(["text", "json", "ndjson"]),
    default="text",
    show_default=True,
    help="Output format (use json/ndjson for structured output)",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Suppress non-error output",
)
@click.option(
    "--connect-timeout",
    envvar="HANDLER_CONNECT_TIMEOUT",
    metavar="SECONDS|none",
    help="HTTP connect timeout in seconds (env: HANDLER_CONNECT_TIMEOUT)",
)
@click.option(
    "--read-timeout",
    envvar="HANDLER_READ_TIMEOUT",
    metavar="SECONDS|none",
    help="HTTP read timeout for non-streaming calls (env: HANDLER_READ_TIMEOUT)",
)
@click.option(
    "--write-timeout",
    envvar="HANDLER_WRITE_TIMEOUT",
    metavar="SECONDS|none",
    help="HTTP write timeout in seconds (env: HANDLER_WRITE_TIMEOUT)",
)
@click.option(
    "--pool-timeout",
    envvar="HANDLER_POOL_TIMEOUT",
    metavar="SECONDS|none",
    help="HTTP connection pool timeout in seconds (env: HANDLER_POOL_TIMEOUT)",
)
@click.option(
    "--stream-read-timeout",
    envvar="HANDLER_STREAM_READ_TIMEOUT",
    metavar="SECONDS|none",
    help="HTTP read timeout for streaming calls; default is none (env: HANDLER_STREAM_READ_TIMEOUT)",
)
@click.pass_context
def cli(
    ctx: click.Context,
    verbose: bool,
    debug: bool,
    output_format: OutputFormat,
    quiet: bool,
    connect_timeout: str | None,
    read_timeout: str | None,
    write_timeout: str | None,
    pool_timeout: str | None,
    stream_read_timeout: str | None,
) -> None:
    """Handler - A2A protocol client CLI."""
    ctx.ensure_object(dict)
    ctx.obj["output_format"] = output_format
    ctx.obj["quiet"] = quiet
    configure_output(output_format=output_format, quiet=quiet)
    configure_http_timeouts(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        write_timeout=write_timeout,
        pool_timeout=pool_timeout,
        stream_read_timeout=stream_read_timeout,
    )

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
def version() -> None:
    """Display the current version.

    \b
    Examples:
      $ handler version
    """
    output = Output()
    output.json({"version": __version__})


@cli.command()
def docs() -> None:
    """Open the Handler documentation in your browser.

    \b
    Examples:
      $ handler docs
    """
    opened = webbrowser.open(DOCS_URL)
    output = Output()
    output.json({"url": DOCS_URL, "opened": opened})


def _upgrade_command() -> list[str] | None:
    """Return the preferred package manager command for upgrading Handler."""
    if shutil.which("uv"):
        return ["uv", "tool", "upgrade", PACKAGE_NAME]
    if shutil.which("pipx"):
        return ["pipx", "upgrade", PACKAGE_NAME]
    return None


@cli.command()
def update() -> None:
    """Update Handler to the latest published version.

    \b
    Examples:
      $ handler update
      $ handler upgrade
    """
    output = Output()
    command = _upgrade_command()
    if command is None:
        output.error(
            code="installer_not_found",
            message="Could not find uv or pipx to update Handler.",
            suggestion=(
                "Install uv or pipx, then run `uv tool upgrade a2a-handler` "
                "or `pipx upgrade a2a-handler`."
            ),
        )
        raise SystemExit(1)

    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        output.error(
            code="update_failed",
            message="Handler update command failed.",
            details={
                "command": command,
                "returncode": result.returncode,
            },
        )
        raise SystemExit(result.returncode)


cli.add_command(update, name="upgrade")


@cli.command()
@click.option(
    "--bearer-env", "-b", help="Env var containing bearer token for agent auth"
)
@click.option(
    "--server",
    "-s",
    "connect_servers",
    multiple=True,
    help="Named server to connect on startup (repeatable)",
)
@click.option("--url", help="URL to pre-connect on startup")
def tui(
    bearer_env: str | None,
    connect_servers: tuple[str, ...],
    url: str | None,
) -> None:
    """Launch the interactive terminal interface.

    \b
    Examples:
      $ handler tui
      $ handler tui --server my_agent
      $ handler tui --server my_agent --server other_agent
      $ handler tui --url http://localhost:8000
      $ handler tui --bearer-env MY_TOKEN
    """
    log.info("Launching TUI")
    logging.getLogger().handlers = []
    bearer_token = os.environ.get(bearer_env) if bearer_env else None
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

    \b
    Examples:
      $ handler web
      $ handler web --port 9000
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
