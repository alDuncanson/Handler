"""Tests for CLI introspection commands."""

from click.testing import CliRunner

from a2a_handler.cli import cli


def test_schema_lists_known_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--output", "json", "schema"])

    assert result.exit_code == 0
    assert '"commands"' in result.output
    assert '"message send"' in result.output
    assert '"task get"' in result.output


def test_describe_returns_command_metadata() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--output", "json", "describe", "message", "send"])

    assert result.exit_code == 0
    assert '"path": "message send"' in result.output
    assert '"params"' in result.output


def test_describe_unknown_command_path_errors() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--output", "json", "describe", "unknown", "cmd"])

    assert result.exit_code == 1
    assert '"code": "unknown_command_path"' in result.output
