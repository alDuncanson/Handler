"""Session commands for managing saved session state."""

from typing import Optional

import rich_click as click

from a2a_handler.common import Output
from a2a_handler.common.input_validation import InputValidationError, validate_agent_url
from a2a_handler.session import clear_session, get_session, get_session_store

from ._helpers import handle_validation_error


@click.group()
def session() -> None:
    """Manage saved session state."""
    pass


@session.command("list")
def session_list() -> None:
    """List all saved sessions."""
    output = Output()
    store = get_session_store()
    sessions = store.list_all()

    if not sessions:
        output.dim("No saved sessions")
        return

    output.header(f"Saved Sessions ({len(sessions)})")
    for s in sessions:
        output.blank()
        output.subheader(s.agent_url)
        if s.context_id:
            output.field("Context ID", s.context_id, dim_value=True)
        if s.task_id:
            output.field("Task ID", s.task_id, dim_value=True)


@session.command("show")
@click.argument("agent_url")
def session_show(agent_url: str) -> None:
    """Display session state for an agent."""
    output = Output()
    try:
        validate_agent_url(agent_url)
    except InputValidationError as error:
        handle_validation_error(error, output)
        raise click.Abort() from error

    s = get_session(agent_url)
    output.header(f"Session for {agent_url}")
    output.field("Context ID", s.context_id or "none", dim_value=not s.context_id)
    output.field("Task ID", s.task_id or "none", dim_value=not s.task_id)


@session.command("clear")
@click.argument("agent_url", required=False)
@click.option("--all", "-a", "clear_all", is_flag=True, help="Clear all sessions")
def session_clear(agent_url: Optional[str], clear_all: bool) -> None:
    """Clear saved session state."""
    output = Output()
    if clear_all:
        clear_session()
        output.success("Cleared all sessions")
    elif agent_url:
        try:
            validate_agent_url(agent_url)
        except InputValidationError as error:
            handle_validation_error(error, output)
            raise click.Abort() from error

        clear_session(agent_url)
        output.success(f"Cleared session for {agent_url}")
    else:
        output.warning("Provide AGENT_URL or use --all to clear sessions")
