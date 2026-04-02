"""Tests for CLI server management commands."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from a2a_handler.cli.server import server


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def servers_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def servers_file(servers_dir: Path) -> Path:
    path = servers_dir / "servers.toml"
    path.write_text(
        """
version = 1

[servers.alpha]
url = "http://localhost:8000"

[servers.alpha.auth]
type = "bearer"
value = "alpha-token"

[servers.beta]
url = "http://localhost:9000"
""".strip()
    )
    return path


# ---------------------------------------------------------------------------
# server list
# ---------------------------------------------------------------------------


class TestServerList:
    def test_list_empty(self, runner: CliRunner, servers_dir: Path) -> None:
        from unittest.mock import patch

        from a2a_handler.servers import ServerCatalog

        with patch(
            "a2a_handler.cli.server.load_server_catalog",
            return_value=ServerCatalog(),
        ):
            result = runner.invoke(server, ["list"])

        assert result.exit_code == 0

    def test_list_shows_configured_servers(
        self, runner: CliRunner, servers_dir: Path
    ) -> None:
        from unittest.mock import patch

        servers_file = servers_dir / "servers.toml"
        servers_file.write_text(
            'version = 1\n\n[servers.demo]\nurl = "http://localhost:8000"\n'
        )

        from a2a_handler.servers import load_server_catalog

        with patch(
            "a2a_handler.cli.server.load_server_catalog",
        ) as mock_catalog:
            mock_catalog.return_value = load_server_catalog(servers_dir)
            result = runner.invoke(server, ["list"])

        assert result.exit_code == 0
        assert "demo" in result.output
        assert "localhost:8000" in result.output


# ---------------------------------------------------------------------------
# server show
# ---------------------------------------------------------------------------


class TestServerShow:
    def test_show_existing(self, runner: CliRunner, servers_dir: Path) -> None:
        from unittest.mock import patch

        from a2a_handler.servers import load_server_catalog

        servers_file = servers_dir / "servers.toml"
        servers_file.write_text(
            'version = 1\n\n[servers.demo]\nurl = "http://localhost:8000"\n'
        )

        with patch(
            "a2a_handler.cli.server.load_server_catalog",
            return_value=load_server_catalog(servers_dir),
        ):
            result = runner.invoke(server, ["show", "demo"])

        assert result.exit_code == 0
        assert "demo" in result.output
        assert "localhost:8000" in result.output

    def test_show_not_found(self, runner: CliRunner) -> None:
        from unittest.mock import patch

        from a2a_handler.servers import ServerCatalog

        with patch(
            "a2a_handler.cli.server.load_server_catalog",
            return_value=ServerCatalog(),
        ):
            result = runner.invoke(server, ["show", "missing"])

        assert result.exit_code == 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# server add
# ---------------------------------------------------------------------------


class TestServerAdd:
    def test_add_creates_file(self, runner: CliRunner, servers_dir: Path) -> None:
        from unittest.mock import patch

        path = servers_dir / "servers.toml"
        with patch("a2a_handler.cli.server._resolve_servers_path", return_value=path):
            result = runner.invoke(
                server, ["add", "demo", "--url", "http://localhost:8000"]
            )

        assert result.exit_code == 0
        assert path.exists()

        data = tomllib.loads(path.read_text())
        assert data["servers"]["demo"]["url"] == "http://localhost:8000"

    def test_add_with_bearer(self, runner: CliRunner, servers_dir: Path) -> None:
        import os
        from unittest.mock import patch
        from unittest.mock import patch as mock_patch

        path = servers_dir / "servers.toml"
        with patch("a2a_handler.cli.server._resolve_servers_path", return_value=path):
            with mock_patch.dict(os.environ, {"TEST_BEARER": "tok"}):
                result = runner.invoke(
                    server,
                    [
                        "add",
                        "demo",
                        "--url",
                        "http://localhost:8000",
                        "--bearer-env",
                        "TEST_BEARER",
                    ],
                )

        assert result.exit_code == 0
        data = tomllib.loads(path.read_text())
        assert data["servers"]["demo"]["auth"]["type"] == "bearer"
        assert data["servers"]["demo"]["auth"]["env"] == "TEST_BEARER"

    def test_add_with_api_key(self, runner: CliRunner, servers_dir: Path) -> None:
        import os
        from unittest.mock import patch
        from unittest.mock import patch as mock_patch

        path = servers_dir / "servers.toml"
        with patch("a2a_handler.cli.server._resolve_servers_path", return_value=path):
            with mock_patch.dict(os.environ, {"TEST_API_KEY": "key-123"}):
                result = runner.invoke(
                    server,
                    [
                        "add",
                        "demo",
                        "--url",
                        "http://localhost:8000",
                        "--api-key-env",
                        "TEST_API_KEY",
                        "--api-key-header",
                        "X-Custom",
                    ],
                )

        assert result.exit_code == 0
        data = tomllib.loads(path.read_text())
        assert data["servers"]["demo"]["auth"]["type"] == "api_key"
        assert data["servers"]["demo"]["auth"]["env"] == "TEST_API_KEY"
        assert data["servers"]["demo"]["auth"]["header"] == "X-Custom"

    def test_add_with_mtls(self, runner: CliRunner, servers_dir: Path) -> None:
        from unittest.mock import patch

        path = servers_dir / "servers.toml"
        with patch("a2a_handler.cli.server._resolve_servers_path", return_value=path):
            result = runner.invoke(
                server,
                [
                    "add",
                    "demo",
                    "--url",
                    "https://secure.example.com",
                    "--cert",
                    "/path/to/cert.pem",
                    "--key",
                    "/path/to/key.pem",
                ],
            )

        assert result.exit_code == 0
        data = tomllib.loads(path.read_text())
        assert data["servers"]["demo"]["auth"]["type"] == "mtls"
        assert data["servers"]["demo"]["auth"]["cert"] == "/path/to/cert.pem"
        assert data["servers"]["demo"]["auth"]["key"] == "/path/to/key.pem"

    def test_add_appends_to_existing_file(
        self, runner: CliRunner, servers_file: Path
    ) -> None:
        from unittest.mock import patch

        with patch(
            "a2a_handler.cli.server._resolve_servers_path",
            return_value=servers_file,
        ):
            result = runner.invoke(
                server, ["add", "gamma", "--url", "http://localhost:7000"]
            )

        assert result.exit_code == 0
        data = tomllib.loads(servers_file.read_text())
        assert "alpha" in data["servers"]
        assert "beta" in data["servers"]
        assert "gamma" in data["servers"]
        assert data["servers"]["gamma"]["url"] == "http://localhost:7000"

    def test_add_rejects_duplicate(self, runner: CliRunner, servers_file: Path) -> None:
        from unittest.mock import patch

        with patch(
            "a2a_handler.cli.server._resolve_servers_path",
            return_value=servers_file,
        ):
            result = runner.invoke(
                server, ["add", "alpha", "--url", "http://localhost:5000"]
            )

        assert result.exit_code == 0
        assert "already exists" in result.output.lower()


# ---------------------------------------------------------------------------
# server remove
# ---------------------------------------------------------------------------


class TestServerRemove:
    def test_remove_existing(self, runner: CliRunner, servers_file: Path) -> None:
        from unittest.mock import patch

        with patch(
            "a2a_handler.cli.server._resolve_servers_path",
            return_value=servers_file,
        ):
            result = runner.invoke(server, ["remove", "beta"])

        assert result.exit_code == 0

        data = tomllib.loads(servers_file.read_text())
        assert "beta" not in data.get("servers", {})
        assert "alpha" in data["servers"]

    def test_remove_not_found(self, runner: CliRunner, servers_file: Path) -> None:
        from unittest.mock import patch

        with patch(
            "a2a_handler.cli.server._resolve_servers_path",
            return_value=servers_file,
        ):
            result = runner.invoke(server, ["remove", "missing"])

        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_remove_missing_file(self, runner: CliRunner, servers_dir: Path) -> None:
        from unittest.mock import patch

        path = servers_dir / "servers.toml"
        with patch("a2a_handler.cli.server._resolve_servers_path", return_value=path):
            result = runner.invoke(server, ["remove", "demo"])

        assert result.exit_code == 0
        assert "No server file" in result.output


# ---------------------------------------------------------------------------
# server validate
# ---------------------------------------------------------------------------


class TestServerValidate:
    def test_validate_empty(self, runner: CliRunner) -> None:
        from unittest.mock import patch

        from a2a_handler.servers import ServerCatalog

        with patch(
            "a2a_handler.cli.server.load_server_catalog",
            return_value=ServerCatalog(),
        ):
            result = runner.invoke(server, ["validate"])

        assert result.exit_code == 0

    def test_validate_all_ok(self, runner: CliRunner, servers_dir: Path) -> None:
        from unittest.mock import patch

        from a2a_handler.servers import load_server_catalog

        servers_file = servers_dir / "servers.toml"
        servers_file.write_text(
            'version = 1\n\n[servers.demo]\nurl = "http://localhost:8000"\n'
        )

        with patch(
            "a2a_handler.cli.server.load_server_catalog",
            return_value=load_server_catalog(servers_dir),
        ):
            result = runner.invoke(server, ["validate"])

        assert result.exit_code == 0
        assert "demo" in result.output
