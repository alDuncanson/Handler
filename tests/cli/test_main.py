"""Tests for top-level CLI commands."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch
from unittest.mock import patch as mock_patch

import pytest
from click.testing import CliRunner

from a2a_handler.cli._helpers import build_http_client, build_streaming_http_client
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


def test_tui_loads_bearer_token_from_workspace_dotenv(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TUI should load .env files relative to the launched workspace."""
    workspace = tmp_path / "repo"
    nested_dir = workspace / "src"
    nested_dir.mkdir(parents=True)
    (workspace / ".env").write_text("TEST_BEARER=dotenv-token\n")
    monkeypatch.chdir(nested_dir)
    monkeypatch.delenv("TEST_BEARER", raising=False)

    with patch("a2a_handler.cli.HandlerTUI") as mock_tui_cls:
        result = runner.invoke(cli, ["tui", "--bearer-env", "TEST_BEARER"])

    assert result.exit_code == 0
    mock_tui_cls.assert_called_once_with(
        initial_bearer_token="dotenv-token",
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


def test_version_json_output(runner: CliRunner) -> None:
    """Version command emits JSON when requested."""
    result = runner.invoke(cli, ["--output", "json", "version"])

    assert result.exit_code == 0
    assert '"version"' in result.output


def test_docs_opens_deployed_documentation(runner: CliRunner) -> None:
    """Docs command opens the hosted documentation URL."""
    with patch("a2a_handler.cli.webbrowser.open", return_value=True) as mock_open:
        result = runner.invoke(cli, ["docs"])

    assert result.exit_code == 0
    mock_open.assert_called_once_with("https://handler.alduncanson.com/")
    assert '"url": "https://handler.alduncanson.com/"' in result.output
    assert '"opened": true' in result.output


def test_timeout_flags_configure_http_clients(runner: CliRunner) -> None:
    """Global timeout flags configure standard and streaming HTTP clients."""
    result = runner.invoke(
        cli,
        [
            "--connect-timeout",
            "10",
            "--read-timeout",
            "11",
            "--write-timeout",
            "12",
            "--pool-timeout",
            "13",
            "--stream-read-timeout",
            "none",
            "version",
        ],
    )

    assert result.exit_code == 0
    standard_client = build_http_client()
    assert standard_client.timeout.connect == 10
    assert standard_client.timeout.read == 11
    assert standard_client.timeout.write == 12
    assert standard_client.timeout.pool == 13
    assert build_streaming_http_client().timeout.read is None


def test_timeout_env_vars_configure_http_clients(runner: CliRunner) -> None:
    """Timeout environment variables configure HTTP clients."""
    result = runner.invoke(
        cli,
        ["version"],
        env={
            "HANDLER_CONNECT_TIMEOUT": "20",
            "HANDLER_READ_TIMEOUT": "21",
            "HANDLER_WRITE_TIMEOUT": "22",
            "HANDLER_POOL_TIMEOUT": "23",
            "HANDLER_STREAM_READ_TIMEOUT": "24",
        },
    )

    assert result.exit_code == 0
    standard_client = build_http_client()
    assert standard_client.timeout.connect == 20
    assert standard_client.timeout.read == 21
    assert standard_client.timeout.write == 22
    assert standard_client.timeout.pool == 23
    assert build_streaming_http_client().timeout.read == 24


def test_timeout_env_vars_load_from_workspace_dotenv_before_click_parses(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timeout envvars in .env are loaded before Click resolves options."""
    workspace = tmp_path / "repo"
    nested_dir = workspace / "src"
    nested_dir.mkdir(parents=True)
    (workspace / ".env").write_text(
        "HANDLER_CONNECT_TIMEOUT=30\n"
        "HANDLER_READ_TIMEOUT=31\n"
        "HANDLER_WRITE_TIMEOUT=32\n"
        "HANDLER_POOL_TIMEOUT=33\n"
        "HANDLER_STREAM_READ_TIMEOUT=34\n"
    )
    monkeypatch.chdir(nested_dir)
    for name in (
        "HANDLER_CONNECT_TIMEOUT",
        "HANDLER_READ_TIMEOUT",
        "HANDLER_WRITE_TIMEOUT",
        "HANDLER_POOL_TIMEOUT",
        "HANDLER_STREAM_READ_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)

    result = runner.invoke(cli, ["version"])

    assert result.exit_code == 0
    standard_client = build_http_client()
    assert standard_client.timeout.connect == 30
    assert standard_client.timeout.read == 31
    assert standard_client.timeout.write == 32
    assert standard_client.timeout.pool == 33
    assert build_streaming_http_client().timeout.read == 34


def test_update_uses_uv_when_available(runner: CliRunner) -> None:
    """Update command uses uv tool upgrade when uv is available."""
    completed = subprocess.CompletedProcess(
        args=["uv", "tool", "upgrade", "a2a-handler"],
        returncode=0,
        stdout="upgraded\n",
        stderr="",
    )
    with patch("a2a_handler.cli.shutil.which") as mock_which:
        mock_which.side_effect = lambda name: f"/bin/{name}" if name == "uv" else None
        with patch(
            "a2a_handler.cli.subprocess.run", return_value=completed
        ) as mock_run:
            result = runner.invoke(cli, ["update"])

    assert result.exit_code == 0
    mock_run.assert_called_once_with(
        ["uv", "tool", "upgrade", "a2a-handler"],
        check=False,
    )
    assert result.output == ""


def test_upgrade_alias_uses_pipx_when_uv_is_unavailable(runner: CliRunner) -> None:
    """Upgrade alias falls back to pipx when uv is unavailable."""
    completed = subprocess.CompletedProcess(
        args=["pipx", "upgrade", "a2a-handler"],
        returncode=0,
        stdout="upgraded\n",
        stderr="",
    )
    with patch("a2a_handler.cli.shutil.which") as mock_which:
        mock_which.side_effect = lambda name: f"/bin/{name}" if name == "pipx" else None
        with patch(
            "a2a_handler.cli.subprocess.run", return_value=completed
        ) as mock_run:
            result = runner.invoke(cli, ["upgrade"])

    assert result.exit_code == 0
    mock_run.assert_called_once_with(
        ["pipx", "upgrade", "a2a-handler"],
        check=False,
    )
    assert result.output == ""


def test_update_errors_when_no_supported_installer_is_available(
    runner: CliRunner,
) -> None:
    """Update command reports a helpful error when uv and pipx are missing."""
    with patch("a2a_handler.cli.shutil.which", return_value=None):
        result = runner.invoke(cli, ["update"])

    assert result.exit_code == 1
    assert "Could not find uv or pipx" in result.output
