"""Tests for top-level CLI commands."""

import os
from unittest.mock import patch
from unittest.mock import patch as mock_patch

import pytest
from click.testing import CliRunner

from a2a_handler.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI runner."""
    return CliRunner()


def test_tui_passes_bearer_token_to_app(runner: CliRunner) -> None:
    """TUI command passes bearer token through to app initialization."""
    with patch("a2a_handler.cli.HandlerTUI") as mock_tui_cls:
        with mock_patch.dict(os.environ, {"TEST_BEARER": "token-123"}):
            result = runner.invoke(cli, ["tui", "--bearer-env", "TEST_BEARER"])

        assert result.exit_code == 0
        mock_tui_cls.assert_called_once_with(
            initial_bearer_token="token-123",
            connect_servers=None,
            connect_url=None,
        )
        mock_tui_cls.return_value.run.assert_called_once()


def test_version_flag(runner: CliRunner) -> None:
    """--version flag prints version and exits."""
    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "handler" in result.output.lower()
    assert "version" in result.output.lower()


def test_version_output(runner: CliRunner) -> None:
    """Version command emits JSON output."""
    result = runner.invoke(cli, ["version"])

    assert result.exit_code == 0
    assert '"version"' in result.output
