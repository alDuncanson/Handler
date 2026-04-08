"""Tests for workspace-local dotenv loading."""

import os

from a2a_handler.common.dotenv import load_runtime_dotenv


def test_load_runtime_dotenv_searches_from_current_workspace(
    tmp_path, monkeypatch
) -> None:
    """Nested workspaces should find the nearest parent .env file."""
    workspace = tmp_path / "repo"
    nested_dir = workspace / "src" / "pkg"
    nested_dir.mkdir(parents=True)
    (workspace / ".env").write_text("CLIENT_ID=workspace-client\n")
    monkeypatch.chdir(nested_dir)
    monkeypatch.delenv("CLIENT_ID", raising=False)

    assert load_runtime_dotenv() is True
    assert os.environ["CLIENT_ID"] == "workspace-client"


def test_load_runtime_dotenv_keeps_existing_environment_values(
    tmp_path, monkeypatch
) -> None:
    """Explicit environment variables should win over workspace .env values."""
    workspace = tmp_path / "repo"
    nested_dir = workspace / "src"
    nested_dir.mkdir(parents=True)
    (workspace / ".env").write_text(
        "CLIENT_ID=dotenv-client\nCLIENT_SECRET=dotenv-secret\n"
    )
    monkeypatch.chdir(nested_dir)
    monkeypatch.setenv("CLIENT_ID", "process-client")
    monkeypatch.delenv("CLIENT_SECRET", raising=False)

    assert load_runtime_dotenv() is True
    assert os.environ["CLIENT_ID"] == "process-client"
    assert os.environ["CLIENT_SECRET"] == "dotenv-secret"


def test_load_runtime_dotenv_returns_false_without_workspace_file(
    tmp_path, monkeypatch
) -> None:
    """Missing .env files should be treated as an expected no-op."""
    monkeypatch.chdir(tmp_path)

    assert load_runtime_dotenv() is False
