"""Tests for server loading and default-auth resolution."""

from pathlib import Path

from a2a_handler.auth import AuthType
from a2a_handler.servers import (
    ServerAuthConfig,
    ServerDefinition,
    ServerSource,
    find_git_root,
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


def test_load_server_catalog_is_empty_without_configured_servers(
    tmp_path: Path, monkeypatch
) -> None:
    """The catalog contains only user-configured servers, with nothing injected."""
    monkeypatch.setattr("a2a_handler.servers.DEFAULT_SERVER_DIRECTORY", tmp_path)

    catalog = load_server_catalog()

    assert catalog.global_servers == ()
    assert catalog.repository_servers == ()


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


def test_load_servers_parses_basic_entry(tmp_path: Path) -> None:
    """HTTP basic server tables load with a username and password env var."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.legacy]
url = "https://legacy.example.com/agent"

[servers.legacy.auth]
type = "basic"
username = "alice"
env = "LEGACY_PASSWORD"
""".strip()
    )
    servers = load_servers(tmp_path, ServerSource.GLOBAL)
    assert len(servers) == 1
    assert servers[0].auth is not None
    assert servers[0].auth.auth_type == AuthType.BASIC
    assert servers[0].auth.username == "alice"
    assert servers[0].auth.env_var == "LEGACY_PASSWORD"


def test_load_servers_skips_basic_without_username(tmp_path: Path) -> None:
    """Basic auth without a username is rejected."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.legacy]
url = "https://legacy.example.com/agent"

[servers.legacy.auth]
type = "basic"
env = "LEGACY_PASSWORD"
""".strip()
    )
    servers = load_servers(tmp_path, ServerSource.GLOBAL)
    assert servers == []


def test_load_servers_rejects_username_outside_basic(tmp_path: Path) -> None:
    """auth.username only makes sense for basic auth."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.oops]
url = "https://example.com/agent"

[servers.oops.auth]
type = "bearer"
username = "alice"
env = "TOKEN"
""".strip()
    )
    servers = load_servers(tmp_path, ServerSource.GLOBAL)
    assert servers == []


def test_resolve_basic_server_credentials(tmp_path: Path, monkeypatch) -> None:
    """Basic server credentials resolve the password from the env var."""
    monkeypatch.setenv("LEGACY_PASSWORD", "resolved-password")

    server_def = ServerDefinition(
        server_id="global:legacy",
        source=ServerSource.GLOBAL,
        name="legacy",
        agent_url="https://legacy.example.com/agent",
        auth=ServerAuthConfig(
            auth_type=AuthType.BASIC,
            username="alice",
            env_var="LEGACY_PASSWORD",
        ),
        origin_label="Global",
    )
    credentials, warning = resolve_server_credentials(server_def)
    assert warning is None
    assert credentials is not None
    assert credentials.auth_type == AuthType.BASIC
    assert credentials.username == "alice"
    assert credentials.value == "resolved-password"


def test_resolve_basic_warns_when_password_env_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """A missing basic password env var yields a warning, not credentials."""
    monkeypatch.delenv("LEGACY_PASSWORD", raising=False)

    server_def = ServerDefinition(
        server_id="global:legacy",
        source=ServerSource.GLOBAL,
        name="legacy",
        agent_url="https://legacy.example.com/agent",
        auth=ServerAuthConfig(
            auth_type=AuthType.BASIC,
            username="alice",
            env_var="LEGACY_PASSWORD",
        ),
        origin_label="Global",
    )
    credentials, warning = resolve_server_credentials(server_def)
    assert credentials is None
    assert warning is not None
    assert "LEGACY_PASSWORD" in warning


def test_load_servers_parses_oidc_entry(tmp_path: Path) -> None:
    """OIDC server tables load with an issuer URL and env var names."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.sso]
url = "https://sso.example.com/agent"

[servers.sso.auth]
type = "oidc"
issuer_url = "https://auth.example.com"
client_id_env = "SSO_CLIENT_ID"
client_secret_env = "SSO_CLIENT_SECRET"
scopes = ["openid", "profile"]
""".strip()
    )
    servers = load_servers(tmp_path, ServerSource.GLOBAL)
    assert len(servers) == 1
    assert servers[0].auth is not None
    assert servers[0].auth.auth_type == AuthType.OIDC
    assert servers[0].auth.issuer_url == "https://auth.example.com"
    assert servers[0].auth.client_id_env == "SSO_CLIENT_ID"
    assert servers[0].auth.client_secret_env == "SSO_CLIENT_SECRET"
    assert servers[0].auth.scopes == ["openid", "profile"]


def test_load_servers_skips_oidc_without_issuer(tmp_path: Path) -> None:
    """OIDC auth without an issuer URL is rejected."""
    server_path = tmp_path / "servers.toml"
    server_path.write_text(
        """
version = 1

[servers.sso]
url = "https://sso.example.com/agent"

[servers.sso.auth]
type = "oidc"
client_id_env = "SSO_CLIENT_ID"
client_secret_env = "SSO_CLIENT_SECRET"
""".strip()
    )
    servers = load_servers(tmp_path, ServerSource.GLOBAL)
    assert servers == []


def test_resolve_oidc_server_credentials(tmp_path: Path, monkeypatch) -> None:
    """OIDC server credentials resolve from env vars with the issuer URL."""
    monkeypatch.setenv("SSO_CLIENT_ID", "resolved-id")
    monkeypatch.setenv("SSO_CLIENT_SECRET", "resolved-secret")

    server_def = ServerDefinition(
        server_id="global:sso",
        source=ServerSource.GLOBAL,
        name="sso",
        agent_url="https://sso.example.com/agent",
        auth=ServerAuthConfig(
            auth_type=AuthType.OIDC,
            issuer_url="https://auth.example.com",
            client_id_env="SSO_CLIENT_ID",
            client_secret_env="SSO_CLIENT_SECRET",
            scopes=["openid"],
        ),
        origin_label="Global",
    )
    credentials, warning = resolve_server_credentials(server_def)
    assert warning is None
    assert credentials is not None
    assert credentials.auth_type == AuthType.OIDC
    assert credentials.issuer_url == "https://auth.example.com"
    assert credentials.client_id == "resolved-id"
    assert credentials.client_secret == "resolved-secret"
    assert credentials.scopes == ["openid"]


def test_resolve_oidc_warns_when_client_id_env_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """A missing OIDC client ID env var yields a warning, not credentials."""
    monkeypatch.delenv("SSO_CLIENT_ID", raising=False)
    monkeypatch.setenv("SSO_CLIENT_SECRET", "resolved-secret")

    server_def = ServerDefinition(
        server_id="global:sso",
        source=ServerSource.GLOBAL,
        name="sso",
        agent_url="https://sso.example.com/agent",
        auth=ServerAuthConfig(
            auth_type=AuthType.OIDC,
            issuer_url="https://auth.example.com",
            client_id_env="SSO_CLIENT_ID",
            client_secret_env="SSO_CLIENT_SECRET",
        ),
        origin_label="Global",
    )
    credentials, warning = resolve_server_credentials(server_def)
    assert credentials is None
    assert warning is not None
    assert "SSO_CLIENT_ID" in warning
