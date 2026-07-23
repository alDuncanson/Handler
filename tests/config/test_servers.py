"""Tests for server loading and default-auth resolution."""

from pathlib import Path

from a2a_handler.auth import AuthType
from a2a_handler.servers import (
    DEFAULT_HANDLER_AGENT_NAME,
    DEFAULT_HANDLER_AGENT_URL,
    ServerAuthConfig,
    ServerDefinition,
    ServerSource,
    default_handler_agent_server,
    find_git_root,
    is_default_handler_agent_server,
    load_server_catalog,
    load_servers,
    resolve_server_credentials,
    server_file_path,
)


def test_server_file_path_uses_custom_directory(tmp_path: Path) -> None:
    """Server path uses requested directory."""
    assert server_file_path(tmp_path) == tmp_path / "servers.toml"


def test_load_servers_returns_empty_when_missing(tmp_path: Path) -> None:
    """Missing server file yields an empty list."""
    assert load_servers(tmp_path, ServerSource.GLOBAL) == []


def test_load_servers_parses_valid_entries(tmp_path: Path) -> None:
    """Valid server tables are loaded with auth metadata."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.local]
url = "http://localhost:8000"

[servers.local.auth]
type = "bearer"
env = "LOCAL_TOKEN"

[servers.staging]
url = "https://staging.example.com"

[servers.staging.auth]
type = "api-key"
value = "inline-api-key"
header = "X-Custom-Key"
""".strip()
    )

    servers = load_servers(tmp_path, ServerSource.GLOBAL)

    assert [server_def.name for server_def in servers] == ["local", "staging"]
    assert servers[0].agent_url == "http://localhost:8000"
    assert servers[0].auth is not None
    assert servers[0].auth.auth_type == AuthType.BEARER
    assert servers[0].auth.env_var == "LOCAL_TOKEN"

    assert servers[1].auth is not None
    assert servers[1].auth.auth_type == AuthType.API_KEY
    assert servers[1].auth.header_name == "X-Custom-Key"


def test_load_servers_skips_reserved_api_key_header(tmp_path: Path) -> None:
    """Reserved API key headers are rejected during server parsing."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.bad]
url = "https://api.example.com"

[servers.bad.auth]
type = "api_key"
value = "inline-api-key"
header = "Authorization"
""".strip()
    )

    servers = load_servers(tmp_path, ServerSource.GLOBAL)

    assert servers == []


def test_load_servers_skips_invalid_entries(tmp_path: Path) -> None:
    """Invalid server entries are skipped while valid ones load."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.ok]
url = "http://localhost:8000"

[servers.ok.auth]
type = "bearer"
value = "token"

[servers.bad-url]
url = "not-a-url"

[servers.bad-url.auth]
type = "bearer"
value = "token"

[servers.bad-auth]
url = "http://localhost:9000"

[servers.bad-auth.auth]
type = "unknown"
value = "token"
""".strip()
    )

    servers = load_servers(tmp_path, ServerSource.GLOBAL)

    assert [server_def.name for server_def in servers] == ["ok"]


def test_resolve_server_credentials_from_env(tmp_path: Path, monkeypatch) -> None:
    """Environment-backed bearer auth resolves to runtime credentials."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.prod]
url = "https://api.example.com"

[servers.prod.auth]
type = "bearer"
env = "PROD_TOKEN"
""".strip()
    )
    monkeypatch.setenv("PROD_TOKEN", "env-secret")

    server_def = load_servers(tmp_path, ServerSource.GLOBAL)[0]
    credentials, warning = resolve_server_credentials(server_def)

    assert warning is None
    assert credentials is not None
    assert credentials.auth_type == AuthType.BEARER
    assert credentials.value == "env-secret"


def test_resolve_server_credentials_env_missing_with_literal_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    """Literal auth value is used when env variable is unset."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.fallback]
url = "https://fallback.example.com"

[servers.fallback.auth]
type = "api_key"
env = "MISSING_TOKEN"
value = "inline-fallback"
""".strip()
    )
    monkeypatch.delenv("MISSING_TOKEN", raising=False)

    server_def = load_servers(tmp_path, ServerSource.GLOBAL)[0]
    credentials, warning = resolve_server_credentials(server_def)

    assert warning is None
    assert credentials is not None
    assert credentials.auth_type == AuthType.API_KEY
    assert credentials.value == "inline-fallback"


def test_resolve_server_credentials_warns_when_env_missing_without_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    """Missing env-only auth source reports warning and no credentials."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.envonly]
url = "https://envonly.example.com"

[servers.envonly.auth]
type = "bearer"
env = "ENV_ONLY_TOKEN"
""".strip()
    )
    monkeypatch.delenv("ENV_ONLY_TOKEN", raising=False)

    server_def = load_servers(tmp_path, ServerSource.GLOBAL)[0]
    credentials, warning = resolve_server_credentials(server_def)

    assert credentials is None
    assert warning is not None
    assert "ENV_ONLY_TOKEN" in warning


def test_load_servers_parses_mtls_entry(tmp_path: Path) -> None:
    """mTLS server tables are loaded with cert paths."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.secure]
url = "https://secure.example.com"

[servers.secure.auth]
type = "mtls"
cert = "/path/to/client.crt"
key = "/path/to/client.key"
ca_cert = "/path/to/ca.crt"
""".strip()
    )
    servers = load_servers(tmp_path, ServerSource.GLOBAL)
    assert servers[0].auth is not None
    assert servers[0].auth.auth_type == AuthType.MTLS
    assert servers[0].auth.cert_path == "/path/to/client.crt"
    assert servers[0].auth.key_path == "/path/to/client.key"
    assert servers[0].auth.ca_cert_path == "/path/to/ca.crt"


def test_resolve_mtls_server_credentials(tmp_path: Path) -> None:
    """mTLS server credentials resolve when files exist."""
    import tempfile
    from unittest.mock import patch

    with (
        tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
        tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
    ):
        server_def = ServerDefinition(
            server_id="global:mtls-test",
            source=ServerSource.GLOBAL,
            name="mtls-test",
            agent_url="https://secure.example.com",
            auth=ServerAuthConfig(
                auth_type=AuthType.MTLS,
                cert_path=cert_file.name,
                key_path=key_file.name,
            ),
            origin_label="Global",
        )
        with patch("a2a_handler.auth.AuthCredentials.build_ssl_context"):
            credentials, warning = resolve_server_credentials(server_def)
        assert warning is None
        assert credentials is not None
        assert credentials.auth_type == AuthType.MTLS
        assert credentials.cert_path == cert_file.name
        assert credentials.key_path == key_file.name


def test_resolve_mtls_server_credentials_warns_for_invalid_cert_data(
    tmp_path: Path,
) -> None:
    """mTLS credentials fail closed when the cert chain cannot be loaded."""
    import tempfile

    with (
        tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
        tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
    ):
        server_def = ServerDefinition(
            server_id="global:mtls-bad",
            source=ServerSource.GLOBAL,
            name="mtls-bad",
            agent_url="https://secure.example.com",
            auth=ServerAuthConfig(
                auth_type=AuthType.MTLS,
                cert_path=cert_file.name,
                key_path=key_file.name,
            ),
            origin_label="Global",
        )
        credentials, warning = resolve_server_credentials(server_def)

    assert credentials is None
    assert warning is not None


def test_find_git_root_returns_repo_root(tmp_path: Path, monkeypatch) -> None:
    """find_git_root returns the directory containing .git."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    subdir = tmp_path / "src" / "pkg"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)

    assert find_git_root() == tmp_path


def test_load_server_catalog_separates_repository_and_global_sources(
    tmp_path: Path, monkeypatch
) -> None:
    """Repository and global servers are kept in distinct source buckets."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "servers.toml").write_text(
        """
version = 1

[servers.shared]
url = "http://global:8000"

[servers.global-only]
url = "http://global-only:8000"
""".strip()
    )

    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    local_handler = repo_root / ".handler"
    local_handler.mkdir()
    (local_handler / "servers.toml").write_text(
        """
version = 1

[servers.shared]
url = "http://local:9000"

[servers.local-only]
url = "http://local-only:9000"
""".strip()
    )

    monkeypatch.chdir(repo_root)

    catalog = load_server_catalog(server_directory=global_dir)

    assert [server_def.name for server_def in catalog.repository_servers] == [
        "local-only",
        "shared",
    ]
    assert [server_def.name for server_def in catalog.global_servers] == [
        "global-only",
        "shared",
    ]


def test_load_server_catalog_includes_default_handler_agent(
    tmp_path: Path, monkeypatch
) -> None:
    """The normal catalog includes Handler's built-in local agent entry."""
    monkeypatch.setattr("a2a_handler.servers.DEFAULT_SERVER_DIRECTORY", tmp_path)

    catalog = load_server_catalog()

    assert catalog.global_servers[-1] == default_handler_agent_server()
    assert is_default_handler_agent_server(catalog.global_servers[-1])


def test_load_server_catalog_does_not_duplicate_default_handler_agent_by_name(
    tmp_path: Path, monkeypatch
) -> None:
    """A user-defined Handler Agent entry takes precedence by name."""
    monkeypatch.setattr("a2a_handler.servers.DEFAULT_SERVER_DIRECTORY", tmp_path)
    (tmp_path / "servers.toml").write_text(
        f"""
version = 1

[servers."{DEFAULT_HANDLER_AGENT_NAME}"]
url = "http://localhost:9000"
""".strip()
    )

    catalog = load_server_catalog()

    assert [server_def.name for server_def in catalog.global_servers] == [
        DEFAULT_HANDLER_AGENT_NAME
    ]
    assert not is_default_handler_agent_server(catalog.global_servers[0])


def test_load_server_catalog_does_not_duplicate_default_handler_agent_by_url(
    tmp_path: Path, monkeypatch
) -> None:
    """A user-defined local Handler URL suppresses the built-in entry."""
    monkeypatch.setattr("a2a_handler.servers.DEFAULT_SERVER_DIRECTORY", tmp_path)
    (tmp_path / "servers.toml").write_text(
        f"""
version = 1

[servers.local]
url = "{DEFAULT_HANDLER_AGENT_URL}"
""".strip()
    )

    catalog = load_server_catalog()

    assert [server_def.name for server_def in catalog.global_servers] == ["local"]
    assert not is_default_handler_agent_server(catalog.global_servers[0])


def test_load_servers_parses_oauth2_entry(tmp_path: Path) -> None:
    """OAuth2 server tables are loaded with token URL and env var names."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.apigee]
url = "https://proxy.apigee.net/agent"

[servers.apigee.auth]
type = "oauth2"
token_url = "https://proxy.apigee.net/oauth/token"
client_id_env = "APIGEE_CLIENT_ID"
client_secret_env = "APIGEE_CLIENT_SECRET"
scopes = ["read", "write"]
""".strip()
    )
    servers = load_servers(tmp_path, ServerSource.GLOBAL)
    assert len(servers) == 1
    assert servers[0].auth is not None
    assert servers[0].auth.auth_type == AuthType.OAUTH2
    assert servers[0].auth.token_url == "https://proxy.apigee.net/oauth/token"
    assert servers[0].auth.client_id_env == "APIGEE_CLIENT_ID"
    assert servers[0].auth.client_secret_env == "APIGEE_CLIENT_SECRET"
    assert servers[0].auth.scopes == ["read", "write"]


def test_load_servers_parses_oauth2_without_scopes(tmp_path: Path) -> None:
    """OAuth2 server without scopes is valid."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.simple]
url = "https://proxy.example.com/agent"

[servers.simple.auth]
type = "oauth2"
token_url = "https://proxy.example.com/oauth/token"
client_id_env = "CLIENT_ID"
client_secret_env = "CLIENT_SECRET"
""".strip()
    )
    servers = load_servers(tmp_path, ServerSource.GLOBAL)
    assert len(servers) == 1
    assert servers[0].auth is not None
    assert servers[0].auth.scopes is None


def test_resolve_oauth2_server_credentials(tmp_path: Path, monkeypatch) -> None:
    """OAuth2 server credentials resolve from env vars."""
    monkeypatch.setenv("MY_CLIENT_ID", "resolved-id")
    monkeypatch.setenv("MY_CLIENT_SECRET", "resolved-secret")

    server_def = ServerDefinition(
        server_id="global:oauth-test",
        source=ServerSource.GLOBAL,
        name="oauth-test",
        agent_url="https://proxy.example.com/agent",
        auth=ServerAuthConfig(
            auth_type=AuthType.OAUTH2,
            token_url="https://proxy.example.com/oauth/token",
            client_id_env="MY_CLIENT_ID",
            client_secret_env="MY_CLIENT_SECRET",
            scopes=["read"],
        ),
        origin_label="Global",
    )
    credentials, warning = resolve_server_credentials(server_def)
    assert warning is None
    assert credentials is not None
    assert credentials.auth_type == AuthType.OAUTH2
    assert credentials.client_id == "resolved-id"
    assert credentials.client_secret == "resolved-secret"
    assert credentials.token_url == "https://proxy.example.com/oauth/token"
    assert credentials.scopes == ["read"]


def test_resolve_oauth2_warns_when_client_id_env_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Missing client_id env var reports warning."""
    monkeypatch.delenv("MISSING_ID", raising=False)
    monkeypatch.setenv("MY_SECRET", "secret")

    server_def = ServerDefinition(
        server_id="global:oauth-missing",
        source=ServerSource.GLOBAL,
        name="oauth-missing",
        agent_url="https://proxy.example.com/agent",
        auth=ServerAuthConfig(
            auth_type=AuthType.OAUTH2,
            token_url="https://proxy.example.com/oauth/token",
            client_id_env="MISSING_ID",
            client_secret_env="MY_SECRET",
        ),
        origin_label="Global",
    )
    credentials, warning = resolve_server_credentials(server_def)
    assert credentials is None
    assert warning is not None
    assert "MISSING_ID" in warning


def test_resolve_oauth2_warns_when_client_secret_env_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Missing client_secret env var reports warning."""
    monkeypatch.setenv("MY_ID", "id-value")
    monkeypatch.delenv("MISSING_SECRET", raising=False)

    server_def = ServerDefinition(
        server_id="global:oauth-missing-secret",
        source=ServerSource.GLOBAL,
        name="oauth-missing-secret",
        agent_url="https://proxy.example.com/agent",
        auth=ServerAuthConfig(
            auth_type=AuthType.OAUTH2,
            token_url="https://proxy.example.com/oauth/token",
            client_id_env="MY_ID",
            client_secret_env="MISSING_SECRET",
        ),
        origin_label="Global",
    )
    credentials, warning = resolve_server_credentials(server_def)
    assert credentials is None
    assert warning is not None
    assert "MISSING_SECRET" in warning


def test_load_servers_parses_google_entry(tmp_path: Path) -> None:
    """A google auth entry is parsed with audience and credential source."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.cloudrun]
url = "https://agent-xxxx-uc.a.run.app"

[servers.cloudrun.auth]
type = "google"
audience = "https://agent-xxxx-uc.a.run.app"
credential_source = "adc"
""".strip()
    )

    servers = load_servers(tmp_path, ServerSource.GLOBAL)

    assert len(servers) == 1
    auth = servers[0].auth
    assert auth is not None
    assert auth.auth_type == AuthType.GOOGLE
    assert auth.audience == "https://agent-xxxx-uc.a.run.app"
    assert auth.credential_source == "adc"


def test_load_servers_skips_google_with_forbidden_value(tmp_path: Path) -> None:
    """A google entry that carries a secret value is rejected as invalid."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.bad]
url = "https://agent.example.com"

[servers.bad.auth]
type = "google"
value = "should-not-be-here"
""".strip()
    )

    servers = load_servers(tmp_path, ServerSource.GLOBAL)
    assert servers == []


def test_resolve_server_credentials_google_adc(tmp_path: Path) -> None:
    """Google ADC auth resolves without needing env vars."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.cloudrun]
url = "https://agent-xxxx-uc.a.run.app"

[servers.cloudrun.auth]
type = "google"
audience = "https://agent-xxxx-uc.a.run.app"
""".strip()
    )

    server_def = load_servers(tmp_path, ServerSource.GLOBAL)[0]
    credentials, warning = resolve_server_credentials(server_def)

    assert warning is None
    assert credentials is not None
    assert credentials.auth_type == AuthType.GOOGLE
    assert credentials.audience == "https://agent-xxxx-uc.a.run.app"


def test_resolve_server_credentials_google_service_account_missing_file(
    tmp_path: Path,
) -> None:
    """Google service_account source fails closed when the key file is missing."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.svc]
url = "https://agent.example.com"

[servers.svc.auth]
type = "google"
credential_source = "service_account"
service_account_file = "/nonexistent/sa.json"
""".strip()
    )

    server_def = load_servers(tmp_path, ServerSource.GLOBAL)[0]
    credentials, warning = resolve_server_credentials(server_def)

    assert credentials is None
    assert warning is not None
