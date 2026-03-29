"""Tests for connection loading and default-auth resolution."""

from pathlib import Path

from a2a_handler.auth import AuthType
from a2a_handler.connections import (
    ConnectionAuthConfig,
    ConnectionDefinition,
    ConnectionSource,
    connection_file_path,
    find_git_root,
    load_connection_catalog,
    load_connections,
    resolve_connection_credentials,
)


def test_connection_file_path_uses_custom_directory(tmp_path: Path) -> None:
    """Connection path uses requested directory."""
    assert connection_file_path(tmp_path) == tmp_path / "connections.toml"


def test_load_connections_returns_empty_when_missing(tmp_path: Path) -> None:
    """Missing connection file yields an empty list."""
    assert load_connections(tmp_path, ConnectionSource.GLOBAL) == []


def test_load_connections_parses_valid_entries(tmp_path: Path) -> None:
    """Valid connection tables are loaded with auth metadata."""
    connection_path = tmp_path / "connections.toml"
    connection_path.write_text(
        """
version = 1

[connections.local]
url = "http://localhost:8000"

[connections.local.auth]
type = "bearer"
env = "LOCAL_TOKEN"

[connections.staging]
url = "https://staging.example.com"

[connections.staging.auth]
type = "api-key"
value = "inline-api-key"
header = "X-Custom-Key"
""".strip()
    )

    connections = load_connections(tmp_path, ConnectionSource.GLOBAL)

    assert [connection.name for connection in connections] == ["local", "staging"]
    assert connections[0].agent_url == "http://localhost:8000"
    assert connections[0].auth is not None
    assert connections[0].auth.auth_type == AuthType.BEARER
    assert connections[0].auth.env_var == "LOCAL_TOKEN"

    assert connections[1].auth is not None
    assert connections[1].auth.auth_type == AuthType.API_KEY
    assert connections[1].auth.header_name == "X-Custom-Key"


def test_load_connections_skips_invalid_entries(tmp_path: Path) -> None:
    """Invalid connection entries are skipped while valid ones load."""
    connection_path = tmp_path / "connections.toml"
    connection_path.write_text(
        """
version = 1

[connections.ok]
url = "http://localhost:8000"

[connections.ok.auth]
type = "bearer"
value = "token"

[connections.bad-url]
url = "not-a-url"

[connections.bad-url.auth]
type = "bearer"
value = "token"

[connections.bad-auth]
url = "http://localhost:9000"

[connections.bad-auth.auth]
type = "unknown"
value = "token"
""".strip()
    )

    connections = load_connections(tmp_path, ConnectionSource.GLOBAL)

    assert [connection.name for connection in connections] == ["ok"]


def test_resolve_connection_credentials_from_env(tmp_path: Path, monkeypatch) -> None:
    """Environment-backed bearer auth resolves to runtime credentials."""
    connection_path = tmp_path / "connections.toml"
    connection_path.write_text(
        """
version = 1

[connections.prod]
url = "https://api.example.com"

[connections.prod.auth]
type = "bearer"
env = "PROD_TOKEN"
""".strip()
    )
    monkeypatch.setenv("PROD_TOKEN", "env-secret")

    connection = load_connections(tmp_path, ConnectionSource.GLOBAL)[0]
    credentials, warning = resolve_connection_credentials(connection)

    assert warning is None
    assert credentials is not None
    assert credentials.auth_type == AuthType.BEARER
    assert credentials.value == "env-secret"


def test_resolve_connection_credentials_env_missing_with_literal_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    """Literal auth value is used when env variable is unset."""
    connection_path = tmp_path / "connections.toml"
    connection_path.write_text(
        """
version = 1

[connections.fallback]
url = "https://fallback.example.com"

[connections.fallback.auth]
type = "api_key"
env = "MISSING_TOKEN"
value = "inline-fallback"
""".strip()
    )
    monkeypatch.delenv("MISSING_TOKEN", raising=False)

    connection = load_connections(tmp_path, ConnectionSource.GLOBAL)[0]
    credentials, warning = resolve_connection_credentials(connection)

    assert warning is None
    assert credentials is not None
    assert credentials.auth_type == AuthType.API_KEY
    assert credentials.value == "inline-fallback"


def test_resolve_connection_credentials_warns_when_env_missing_without_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    """Missing env-only auth source reports warning and no credentials."""
    connection_path = tmp_path / "connections.toml"
    connection_path.write_text(
        """
version = 1

[connections.envonly]
url = "https://envonly.example.com"

[connections.envonly.auth]
type = "bearer"
env = "ENV_ONLY_TOKEN"
""".strip()
    )
    monkeypatch.delenv("ENV_ONLY_TOKEN", raising=False)

    connection = load_connections(tmp_path, ConnectionSource.GLOBAL)[0]
    credentials, warning = resolve_connection_credentials(connection)

    assert credentials is None
    assert warning is not None
    assert "ENV_ONLY_TOKEN" in warning


def test_load_connections_parses_mtls_entry(tmp_path: Path) -> None:
    """mTLS connection tables are loaded with cert paths."""
    connection_path = tmp_path / "connections.toml"
    connection_path.write_text(
        """
version = 1

[connections.secure]
url = "https://secure.example.com"

[connections.secure.auth]
type = "mtls"
cert = "/path/to/client.crt"
key = "/path/to/client.key"
ca_cert = "/path/to/ca.crt"
""".strip()
    )
    connections = load_connections(tmp_path, ConnectionSource.GLOBAL)
    assert connections[0].auth is not None
    assert connections[0].auth.auth_type == AuthType.MTLS
    assert connections[0].auth.cert_path == "/path/to/client.crt"
    assert connections[0].auth.key_path == "/path/to/client.key"
    assert connections[0].auth.ca_cert_path == "/path/to/ca.crt"


def test_resolve_mtls_connection_credentials(tmp_path: Path) -> None:
    """mTLS connection credentials resolve when files exist."""
    import tempfile

    with (
        tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
        tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
    ):
        connection = ConnectionDefinition(
            connection_id="global:mtls-test",
            source=ConnectionSource.GLOBAL,
            name="mtls-test",
            agent_url="https://secure.example.com",
            auth=ConnectionAuthConfig(
                auth_type=AuthType.MTLS,
                cert_path=cert_file.name,
                key_path=key_file.name,
            ),
            origin_label="Global",
        )
        credentials, warning = resolve_connection_credentials(connection)
        assert warning is None
        assert credentials is not None
        assert credentials.auth_type == AuthType.MTLS
        assert credentials.cert_path == cert_file.name
        assert credentials.key_path == key_file.name


def test_find_git_root_returns_repo_root(tmp_path: Path, monkeypatch) -> None:
    """find_git_root returns the directory containing .git."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    subdir = tmp_path / "src" / "pkg"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)

    assert find_git_root() == tmp_path


def test_load_connection_catalog_separates_repository_and_global_sources(
    tmp_path: Path, monkeypatch
) -> None:
    """Repository and global connections are kept in distinct source buckets."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "connections.toml").write_text(
        """
version = 1

[connections.shared]
url = "http://global:8000"

[connections.global-only]
url = "http://global-only:8000"
""".strip()
    )

    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    local_handler = repo_root / ".handler"
    local_handler.mkdir()
    (local_handler / "connections.toml").write_text(
        """
version = 1

[connections.shared]
url = "http://local:9000"

[connections.local-only]
url = "http://local-only:9000"
""".strip()
    )

    monkeypatch.chdir(repo_root)

    catalog = load_connection_catalog(connection_directory=global_dir)

    assert [connection.name for connection in catalog.repository_connections] == [
        "local-only",
        "shared",
    ]
    assert [connection.name for connection in catalog.global_connections] == [
        "global-only",
        "shared",
    ]
