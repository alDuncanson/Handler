"""Tests for profile loading and credential resolution."""

from pathlib import Path

from a2a_handler.auth import AuthType
from a2a_handler.profiles import (
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
use_session = false

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
    assert profiles["local"].use_session is False
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
