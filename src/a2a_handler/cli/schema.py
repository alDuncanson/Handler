"""CLI schema/introspection commands for agent runtime discovery."""

from __future__ import annotations

import click

from a2a_handler.common import Output


def _serialize_parameter(param: click.Parameter) -> dict[str, object]:
    """Serialize a click parameter into a machine-readable shape."""
    data: dict[str, object] = {
        "name": param.name,
        "kind": param.param_type_name,
        "required": param.required,
        "nargs": param.nargs,
        "type": str(param.type),
    }
    if isinstance(param, click.Option):
        data["options"] = list(param.opts) + list(param.secondary_opts)
        data["is_flag"] = param.is_flag
        data["multiple"] = param.multiple
        data["help"] = param.help
        if param.default is not None:
            data["default"] = param.default
    elif isinstance(param, click.Argument):
        data["metavar"] = param.metavar or (param.name or "arg").upper()
    return data


def _serialize_command(command: click.Command, path: str) -> dict[str, object]:
    """Serialize a click command with parameters and subcommands."""
    payload: dict[str, object] = {
        "name": command.name,
        "path": path,
        "help": command.help,
        "short_help": command.short_help,
        "params": [_serialize_parameter(param) for param in command.params],
    }
    if isinstance(command, click.Group):
        payload["subcommands"] = sorted(command.commands)
    return payload


def build_cli_schema(root: click.Group) -> dict[str, object]:
    """Build a full schema snapshot for the root CLI group."""
    commands: dict[str, dict[str, object]] = {}
    schema: dict[str, object] = {
        "name": root.name,
        "help": root.help,
        "commands": commands,
    }

    def walk(group: click.Group, prefix: tuple[str, ...] = ()) -> None:
        for name in sorted(group.commands):
            command = group.commands[name]
            path_tokens = (*prefix, name)
            path = " ".join(path_tokens)
            commands[path] = _serialize_command(command, path)
            if isinstance(command, click.Group):
                walk(command, path_tokens)

    walk(root)
    return schema


def resolve_command(
    root: click.Group, path_tokens: tuple[str, ...]
) -> click.Command | None:
    """Resolve a command by path tokens from the root group."""
    current: click.Command = root
    for token in path_tokens:
        if not isinstance(current, click.Group):
            return None
        current = current.commands.get(token)  # type: ignore[assignment]
        if current is None:
            return None
    return current


@click.command()
@click.pass_context
def schema(ctx: click.Context) -> None:
    """Output machine-readable CLI command schema.

    \b
    Examples:
      $ handler schema
      $ handler --output json schema
    """
    root = ctx.find_root().command
    assert isinstance(root, click.Group)
    output = Output()
    output.json(build_cli_schema(root))


@click.command()
@click.argument("command_path", nargs=-1, required=True)
@click.pass_context
def describe(ctx: click.Context, command_path: tuple[str, ...]) -> None:
    """Describe a command path as machine-readable metadata.

    \b
    Examples:
      $ handler describe message send
      $ handler describe task get
      $ handler describe server add
    """
    root = ctx.find_root().command
    assert isinstance(root, click.Group)
    output = Output()

    command = resolve_command(root, command_path)
    if command is None:
        output.error(
            code="unknown_command_path",
            message=f"Unknown command path: {' '.join(command_path)}",
            suggestion="Use `handler schema` to list valid command paths",
        )
        raise click.Abort()

    output.json(_serialize_command(command, " ".join(command_path)))
