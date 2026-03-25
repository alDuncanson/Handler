"""Tests for profile loading and credential resolution."""

from pathlib import Path

from a2a_handler.auth import AuthType
from a2a_handler.profiles import (
    ConnectionProfile,
    ProfileAuthConfig,
    find_git_root,
    load_all_profiles,
    load_profiles,
    profile_file_path,
    resolve_profile_credentials,
)


def test_profile_file_path_uses_custom_directory(tmp_path: Path) -> None:
    """Profile path uses requested directory."""
    assert profile_file_path(tmp_path) == tmp_path / "profiles.toml"


def test_load_profiles_returns_empty_when_missing(tmp_path: Path) -> None:
    """Missing profile file yields empty profile map."""
    assert load_profiles(tmp_path) == {}


def test_load_profiles_parses_valid_entries(tmp_path: Path) -> None:
    """Valid profile tables are loaded with auth metadata."""
    profile_path = tmp_path / "profiles.toml"
    profile_path.write_text(
        """
version = 1

[profiles.local]
url = "http://localhost:8000"

[profiles.local.auth]
type = "bearer"
env = "LOCAL_TOKEN"

[profiles.staging]
url = "https://staging.example.com"

[profiles.staging.auth]
type = "api-key"
value = "inline-api-key"
header = "X-Custom-Key"
""".strip()
    )

    profiles = load_profiles(tmp_path)

    assert set(profiles) == {"local", "staging"}
    assert profiles["local"].agent_url == "http://localhost:8000"
    assert profiles["local"].auth is not None
    assert profiles["local"].auth.auth_type == AuthType.BEARER
    assert profiles["local"].auth.env_var == "LOCAL_TOKEN"

    assert profiles["staging"].auth is not None
    assert profiles["staging"].auth.auth_type == AuthType.API_KEY
    assert profiles["staging"].auth.header_name == "X-Custom-Key"


def test_load_profiles_skips_invalid_entries(tmp_path: Path) -> None:
    """Invalid profile entries are skipped while valid ones load."""
    profile_path = tmp_path / "profiles.toml"
    profile_path.write_text(
        """
version = 1

[profiles.ok]
url = "http://localhost:8000"

[profiles.ok.auth]
type = "bearer"
value = "token"

[profiles.bad-url]
url = "not-a-url"

[profiles.bad-url.auth]
type = "bearer"
value = "token"

[profiles.bad-auth]
url = "http://localhost:9000"

[profiles.bad-auth.auth]
type = "unknown"
value = "token"
""".strip()
    )

    profiles = load_profiles(tmp_path)

    assert set(profiles) == {"ok"}


def test_resolve_profile_credentials_from_env(tmp_path: Path, monkeypatch) -> None:
    """Environment-backed bearer auth resolves to runtime credentials."""
    profile_path = tmp_path / "profiles.toml"
    profile_path.write_text(
        """
version = 1

[profiles.prod]
url = "https://api.example.com"

[profiles.prod.auth]
type = "bearer"
env = "PROD_TOKEN"
""".strip()
    )
    monkeypatch.setenv("PROD_TOKEN", "env-secret")

    profile = load_profiles(tmp_path)["prod"]
    credentials, warning = resolve_profile_credentials(profile)

    assert warning is None
    assert credentials is not None
    assert credentials.auth_type == AuthType.BEARER
    assert credentials.value == "env-secret"


def test_resolve_profile_credentials_env_missing_with_literal_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    """Literal auth value is used when env variable is unset."""
    profile_path = tmp_path / "profiles.toml"
    profile_path.write_text(
        """
version = 1

[profiles.fallback]
url = "https://fallback.example.com"

[profiles.fallback.auth]
type = "api_key"
env = "MISSING_TOKEN"
value = "inline-fallback"
""".strip()
    )
    monkeypatch.delenv("MISSING_TOKEN", raising=False)

    profile = load_profiles(tmp_path)["fallback"]
    credentials, warning = resolve_profile_credentials(profile)

    assert warning is None
    assert credentials is not None
    assert credentials.auth_type == AuthType.API_KEY
    assert credentials.value == "inline-fallback"


def test_resolve_profile_credentials_warns_when_env_missing_without_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    """Missing env-only auth source reports warning and no credentials."""
    profile_path = tmp_path / "profiles.toml"
    profile_path.write_text(
        """
version = 1

[profiles.envonly]
url = "https://envonly.example.com"

[profiles.envonly.auth]
type = "bearer"
env = "ENV_ONLY_TOKEN"
""".strip()
    )
    monkeypatch.delenv("ENV_ONLY_TOKEN", raising=False)

    profile = load_profiles(tmp_path)["envonly"]
    credentials, warning = resolve_profile_credentials(profile)

    assert credentials is None
    assert warning is not None
    assert "ENV_ONLY_TOKEN" in warning


def test_load_profiles_parses_mtls_entry(tmp_path: Path) -> None:
    """mTLS profile tables are loaded with cert paths."""
    profile_path = tmp_path / "profiles.toml"
    profile_path.write_text(
        """
version = 1

[profiles.secure]
url = "https://secure.example.com"

[profiles.secure.auth]
type = "mtls"
cert = "/path/to/client.crt"
key = "/path/to/client.key"
ca_cert = "/path/to/ca.crt"
""".strip()
    )
    profiles = load_profiles(tmp_path)
    assert "secure" in profiles
    assert profiles["secure"].auth is not None
    assert profiles["secure"].auth.auth_type == AuthType.MTLS
    assert profiles["secure"].auth.cert_path == "/path/to/client.crt"
    assert profiles["secure"].auth.key_path == "/path/to/client.key"
    assert profiles["secure"].auth.ca_cert_path == "/path/to/ca.crt"


def test_load_profiles_mtls_without_ca_cert(tmp_path: Path) -> None:
    """mTLS profile without ca_cert is valid."""
    profile_path = tmp_path / "profiles.toml"
    profile_path.write_text(
        """
version = 1

[profiles.nocacert]
url = "https://nocacert.example.com"

[profiles.nocacert.auth]
type = "mtls"
cert = "/path/to/client.crt"
key = "/path/to/client.key"
""".strip()
    )
    profiles = load_profiles(tmp_path)
    assert profiles["nocacert"].auth is not None
    assert profiles["nocacert"].auth.ca_cert_path is None


def test_load_profiles_mtls_missing_key_is_invalid(tmp_path: Path) -> None:
    """mTLS profile missing key path is skipped."""
    profile_path = tmp_path / "profiles.toml"
    profile_path.write_text(
        """
version = 1

[profiles.badmtls]
url = "https://bad.example.com"

[profiles.badmtls.auth]
type = "mtls"
cert = "/path/to/client.crt"
""".strip()
    )
    profiles = load_profiles(tmp_path)
    assert "badmtls" not in profiles


def test_load_profiles_mtls_rejects_env(tmp_path: Path) -> None:
    """mTLS profiles must not use env field."""
    profile_path = tmp_path / "profiles.toml"
    profile_path.write_text(
        """
version = 1

[profiles.badmtls]
url = "https://bad.example.com"

[profiles.badmtls.auth]
type = "mtls"
cert = "/path/to/client.crt"
key = "/path/to/client.key"
env = "SOME_VAR"
""".strip()
    )
    profiles = load_profiles(tmp_path)
    assert "badmtls" not in profiles


def test_resolve_mtls_profile_credentials(tmp_path: Path) -> None:
    """mTLS profile credentials resolve to create_mtls_auth when files exist."""
    import tempfile

    with (
        tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
        tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
    ):
        profile = ConnectionProfile(
            name="mtls-test",
            agent_url="https://secure.example.com",
            auth=ProfileAuthConfig(
                auth_type=AuthType.MTLS,
                cert_path=cert_file.name,
                key_path=key_file.name,
            ),
        )
        credentials, warning = resolve_profile_credentials(profile)
        assert warning is None
        assert credentials is not None
        assert credentials.auth_type == AuthType.MTLS
        assert credentials.cert_path == cert_file.name
        assert credentials.key_path == key_file.name


def test_resolve_mtls_profile_warns_on_missing_cert() -> None:
    """mTLS profile returns warning when cert file doesn't exist."""
    profile = ConnectionProfile(
        name="mtls-bad",
        agent_url="https://secure.example.com",
        auth=ProfileAuthConfig(
            auth_type=AuthType.MTLS,
            cert_path="/nonexistent/cert.pem",
            key_path="/nonexistent/key.pem",
        ),
    )
    credentials, warning = resolve_profile_credentials(profile)
    assert credentials is None
    assert warning is not None
    assert "mtls-bad" in warning


def test_find_git_root_returns_repo_root(tmp_path: Path, monkeypatch) -> None:
    """find_git_root returns the directory containing .git."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    subdir = tmp_path / "src" / "pkg"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)

    assert find_git_root() == tmp_path


def test_find_git_root_returns_none_without_git(tmp_path: Path, monkeypatch) -> None:
    """find_git_root returns None outside a git repo."""
    monkeypatch.chdir(tmp_path)

    assert find_git_root() is None


def test_load_all_profiles_merges_local_over_global(
    tmp_path: Path, monkeypatch
) -> None:
    """Local git-repo profiles override global profiles with the same name."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "profiles.toml").write_text(
        """
version = 1

[profiles.shared]
url = "http://global:8000"

[profiles.shared.auth]
type = "bearer"
value = "global-token"

[profiles.global-only]
url = "http://global-only:8000"
""".strip()
    )

    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    local_handler = repo_root / ".handler"
    local_handler.mkdir()
    (local_handler / "profiles.toml").write_text(
        """
version = 1

[profiles.shared]
url = "http://local:9000"

[profiles.shared.auth]
type = "bearer"
value = "local-token"

[profiles.local-only]
url = "http://local-only:9000"
""".strip()
    )

    monkeypatch.chdir(repo_root)

    profiles = load_all_profiles(profile_directory=global_dir)

    assert set(profiles) == {"shared", "global-only", "local-only"}
    assert profiles["shared"].agent_url == "http://local:9000"
    assert profiles["global-only"].agent_url == "http://global-only:8000"
    assert profiles["local-only"].agent_url == "http://local-only:9000"
