"""Tests for top-level CLI commands."""

from unittest.mock import patch

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
        result = runner.invoke(cli, ["tui", "--bearer", "token-123"])

        assert result.exit_code == 0
        mock_tui_cls.assert_called_once_with(initial_bearer_token="token-123")
        mock_tui_cls.return_value.run.assert_called_once()
