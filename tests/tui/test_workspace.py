"""Tests for repository-local workspace server management."""

from __future__ import annotations

import tomllib
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from a2a_handler.tui.server.workspace import (
    remove_workspace_server,
    rename_workspace_server,
)

SERVERS_TOML = """\
version = 1

[servers.alpha]
url = "http://alpha.example.com"

[servers.beta]
url = "http://beta.example.com"
"""


@pytest.fixture
def servers_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / ".handler" / "servers.toml"
    path.parent.mkdir()
    path.write_text(SERVERS_TOML)
    with patch("a2a_handler.cli.server._resolve_servers_path", return_value=path):
        yield path


def _server_names(path: Path) -> list[str]:
    return sorted(tomllib.loads(path.read_text())["servers"])


def test_rename_moves_the_entry(servers_path: Path) -> None:
    assert rename_workspace_server("alpha", "gamma") == servers_path
    assert _server_names(servers_path) == ["beta", "gamma"]
    data = tomllib.loads(servers_path.read_text())
    assert data["servers"]["gamma"]["url"] == "http://alpha.example.com"


def test_rename_to_the_same_name_leaves_the_file_alone(servers_path: Path) -> None:
    before = servers_path.read_text()
    assert rename_workspace_server("alpha", "alpha") == servers_path
    assert servers_path.read_text() == before


def test_rename_rejects_unknown_server(servers_path: Path) -> None:
    with pytest.raises(KeyError, match="'alpha-x' was not found"):
        rename_workspace_server("alpha-x", "gamma")


def test_rename_rejects_a_taken_name(servers_path: Path) -> None:
    with pytest.raises(ValueError, match="'beta' already exists"):
        rename_workspace_server("alpha", "beta")


@pytest.mark.parametrize("bad_name", ["", "has space", "dots.too", "slash/"])
def test_rename_rejects_names_toml_cannot_key(
    servers_path: Path, bad_name: str
) -> None:
    with pytest.raises(ValueError, match="Workspace server names"):
        rename_workspace_server("alpha", bad_name)
    assert _server_names(servers_path) == ["alpha", "beta"]


def test_remove_deletes_the_entry(servers_path: Path) -> None:
    assert remove_workspace_server("alpha") == servers_path
    assert _server_names(servers_path) == ["beta"]


def test_remove_rejects_unknown_server(servers_path: Path) -> None:
    with pytest.raises(KeyError, match="'nope' was not found"):
        remove_workspace_server("nope")


def test_missing_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "servers.toml"
    with (
        patch("a2a_handler.cli.server._resolve_servers_path", return_value=path),
        pytest.raises(FileNotFoundError, match="No workspace server file"),
    ):
        remove_workspace_server("alpha")


def test_file_without_servers_table_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "servers.toml"
    path.write_text("version = 1\n")
    with (
        patch("a2a_handler.cli.server._resolve_servers_path", return_value=path),
        pytest.raises(KeyError, match="No workspace servers found"),
    ):
        rename_workspace_server("alpha", "beta")
