"""Tests for top-level CLI commands."""

import re
import subprocess
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from a2a_handler.cli import cli

ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def _normalized_output(output: str) -> str:
    """Normalize rich-formatted CLI output for stable assertions."""
    without_ansi = ANSI_ESCAPE_PATTERN.sub("", output)
    return " ".join(without_ansi.split())


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI runner."""
    return CliRunner()


def test_tui_passes_bearer_token_to_app(runner: CliRunner) -> None:
    """TUI command passes bearer token through to app initialization."""
    with patch("a2a_handler.cli.HandlerTUI") as mock_tui_cls:
        result = runner.invoke(cli, ["tui", "--bearer", "token-123"])

        assert result.exit_code == 0
        mock_tui_cls.assert_called_once_with(initial_bearer_token="token-123")
        mock_tui_cls.return_value.run.assert_called_once()


def test_tui_passes_bearer_token_from_command(runner: CliRunner) -> None:
    """TUI command resolves bearer token from subprocess stdout."""
    with (
        patch("a2a_handler.cli.HandlerTUI") as mock_tui_cls,
        patch("a2a_handler.cli.subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["gcloud", "auth", "print-identity-token"],
            returncode=0,
            stdout="token-from-command\n",
            stderr="",
        )

        result = runner.invoke(
            cli,
            ["tui", "--bearer-command", "gcloud auth print-identity-token"],
        )

        assert result.exit_code == 0
        mock_tui_cls.assert_called_once_with(initial_bearer_token="token-from-command")
        mock_tui_cls.return_value.run.assert_called_once()


def test_tui_passes_bearer_token_from_stdin(runner: CliRunner) -> None:
    """TUI command reads bearer token from stdin."""
    with patch("a2a_handler.cli.HandlerTUI") as mock_tui_cls:
        result = runner.invoke(cli, ["tui", "--bearer-stdin"], input="token-stdin\n")

        assert result.exit_code == 0
        mock_tui_cls.assert_called_once_with(initial_bearer_token="token-stdin")
        mock_tui_cls.return_value.run.assert_called_once()


def test_tui_rejects_multiple_bearer_sources(runner: CliRunner) -> None:
    """TUI command rejects multiple bearer token sources."""
    result = runner.invoke(
        cli,
        ["tui", "--bearer", "token-123", "--bearer-stdin"],
    )

    assert result.exit_code == 1
    assert "Use only one of --bearer, --bearer-command, or --bearer-stdin" in (
        _normalized_output(result.output)
    )


def test_tui_reports_bearer_command_failure(runner: CliRunner) -> None:
    """TUI command surfaces subprocess failures from --bearer-command."""
    with patch("a2a_handler.cli.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=2,
            cmd=["gcloud", "auth", "print-identity-token"],
            stderr="permission denied",
        )

        result = runner.invoke(
            cli,
            ["tui", "--bearer-command", "gcloud auth print-identity-token"],
        )

        assert result.exit_code == 1
        assert "--bearer-command failed with exit code 2: permission denied" in (
            _normalized_output(result.output)
        )


def test_tui_rejects_empty_stdin_token(runner: CliRunner) -> None:
    """TUI command rejects empty --bearer-stdin tokens."""
    result = runner.invoke(cli, ["tui", "--bearer-stdin"], input="\n")

    assert result.exit_code == 1
    assert "--bearer-stdin received an empty token" in _normalized_output(result.output)


def test_version_plain_text_default(runner: CliRunner) -> None:
    """Version command defaults to text output."""
    result = runner.invoke(cli, ["version"])

    assert result.exit_code == 0
    assert result.output.strip()
    assert "version" not in result.output.lower()


def test_version_json_output(runner: CliRunner) -> None:
    """Version command supports global json output mode."""
    result = runner.invoke(cli, ["--output", "json", "version"])

    assert result.exit_code == 0
    assert '"type": "data"' in result.output
    assert '"version"' in result.output
