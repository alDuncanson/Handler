"""Session commands for managing saved conversation state."""

from typing import Optional

import click

from a2a_handler.common import Output
from a2a_handler.common.input_validation import InputValidationError, validate_agent_url
from a2a_handler.session import clear_session, get_session, get_session_store

from ._helpers import handle_validation_error, resolve_agent_selection


@click.group()
def session() -> None:
    """Manage saved conversation state."""
    pass


@session.command("list")
def session_list() -> None:
    """List all saved conversation sessions.

    \b
    Examples:
      $ handler session list
    """
    output = Output()
    store = get_session_store()
    sessions = store.list_all()

    if not sessions:
        return

    data: list[dict[str, object]] = []
    for session_entry in sessions:
        session_data: dict[str, object] = {"agent_url": session_entry.agent_url}
        if session_entry.context_id:
            session_data["context_id"] = session_entry.context_id
        if session_entry.task_id:
            session_data["task_id"] = session_entry.task_id
        if session_entry.last_used_at:
            session_data["last_used_at"] = session_entry.last_used_at
        data.append(session_data)

    output.json(data)


@session.command("show")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
def session_show(agent_url: Optional[str], server_name: Optional[str]) -> None:
    """Display saved conversation state for an agent.

    \b
    Examples:
      $ handler session show --server my_agent
      $ handler session show --url http://localhost:8000
    """
    output = Output()

    agent_url = resolve_agent_selection(agent_url, server_name).agent_url

    try:
        validate_agent_url(agent_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    session_entry = get_session(agent_url)

    output.json(
        {
            "agent_url": agent_url,
            "context_id": session_entry.context_id,
            "task_id": session_entry.task_id,
            "last_used_at": session_entry.last_used_at,
        }
    )


@session.command("clear")
@click.option("--url", "agent_url", help="Agent URL")
@click.option("--server", "-s", "server_name", help="Named server from servers.toml")
@click.option("--all", "-a", "clear_all", is_flag=True, help="Clear all sessions")
def session_clear(
    agent_url: Optional[str],
    server_name: Optional[str],
    clear_all: bool,
) -> None:
    """Clear saved conversation state.

    \b
    Examples:
      $ handler session clear --server my_agent
      $ handler session clear --url http://localhost:8000
      $ handler session clear --all
    """
    output = Output()
    if clear_all:
        clear_session()
        output.json({"cleared": "all"})
    elif server_name:
        agent_url = resolve_agent_selection(agent_url, server_name).agent_url
        clear_session(agent_url)
        output.json({"cleared": agent_url})
    elif agent_url:
        try:
            validate_agent_url(agent_url)
        except InputValidationError as error:
            handle_validation_error(error, output)
            raise click.Abort() from error

        clear_session(agent_url)
        output.json({"cleared": agent_url})
    else:
        output.error(
            code="missing_target",
            message="Provide --url or --server, or use --all to clear sessions",
        )
