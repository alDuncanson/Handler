"""Tests for CLI auth commands."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from a2a_handler.cli.auth import auth
from a2a_handler.auth import AuthType, create_bearer_auth, create_api_key_auth
from a2a_handler.session import SessionStore


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def temp_session_store():
    """Create a temporary session store for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        store = SessionStore(session_directory=Path(temp_dir))
        yield store


class TestAuthSet:
    """Tests for auth set command."""

    def test_set_bearer_token(self, runner, temp_session_store):
        """Test setting a bearer token."""
        with patch("a2a_handler.cli.auth.set_credentials") as mock_set:
            result = runner.invoke(
                auth,
                ["set", "http://localhost:8000", "--bearer", "my-secret-token"],
            )

            assert result.exit_code == 0
            assert "Bearer token" in result.output
            mock_set.assert_called_once()
            call_args = mock_set.call_args
            assert call_args[0][0] == "http://localhost:8000"
            assert call_args[0][1].auth_type == AuthType.BEARER
            assert call_args[0][1].value == "my-secret-token"

    def test_set_api_key(self, runner, temp_session_store):
        """Test setting an API key."""
        with patch("a2a_handler.cli.auth.set_credentials") as mock_set:
            result = runner.invoke(
                auth,
                ["set", "http://localhost:8000", "--api-key", "my-api-key"],
            )

            assert result.exit_code == 0
            assert "API key" in result.output
            mock_set.assert_called_once()
            call_args = mock_set.call_args
            assert call_args[0][1].auth_type == AuthType.API_KEY
            assert call_args[0][1].value == "my-api-key"

    def test_set_api_key_with_custom_header(self, runner):
        """Test setting an API key with custom header."""
        with patch("a2a_handler.cli.auth.set_credentials") as mock_set:
            result = runner.invoke(
                auth,
                [
                    "set",
                    "http://localhost:8000",
                    "--api-key",
                    "my-api-key",
                    "--api-key-header",
                    "X-Custom-Key",
                ],
            )

            assert result.exit_code == 0
            assert "X-Custom-Key" in result.output
            call_args = mock_set.call_args
            assert call_args[0][1].header_name == "X-Custom-Key"

    def test_set_both_bearer_and_api_key_fails(self, runner):
        """Test that providing both bearer and API key fails."""
        result = runner.invoke(
            auth,
            [
                "set",
                "http://localhost:8000",
                "--bearer",
                "token",
                "--api-key",
                "key",
            ],
        )

        assert result.exit_code == 1
        assert "not both" in result.output.lower() or "either" in result.output.lower()

    def test_set_neither_bearer_nor_api_key_fails(self, runner):
        """Test that providing neither bearer nor API key fails."""
        result = runner.invoke(auth, ["set", "http://localhost:8000"])

        assert result.exit_code == 1

    def test_set_rejects_invalid_agent_url(self, runner):
        """Test setting credentials rejects malformed agent URL."""
        result = runner.invoke(auth, ["set", "not-a-url", "--bearer", "token"])

        assert result.exit_code == 1
        assert "agent_url must be a valid http(s) URL" in result.output


class TestAuthShow:
    """Tests for auth show command."""

    def test_show_bearer_credentials(self, runner):
        """Test showing bearer credentials."""
        mock_creds = create_bearer_auth("my-secret-token-value")

        with patch("a2a_handler.cli.auth.get_credentials", return_value=mock_creds):
            result = runner.invoke(auth, ["show", "http://localhost:8000"])

            assert result.exit_code == 0
            assert "bearer" in result.output.lower()
            # Check that value is masked
            assert "my-s" in result.output
            assert "alue" in result.output
            assert "my-secret-token-value" not in result.output

    def test_show_api_key_credentials(self, runner):
        """Test showing API key credentials."""
        mock_creds = create_api_key_auth("my-api-key-value", header_name="X-Custom")

        with patch("a2a_handler.cli.auth.get_credentials", return_value=mock_creds):
            result = runner.invoke(auth, ["show", "http://localhost:8000"])

            assert result.exit_code == 0
            assert "api_key" in result.output.lower()
            assert "X-Custom" in result.output

    def test_show_no_credentials(self, runner):
        """Test showing when no credentials exist."""
        with patch("a2a_handler.cli.auth.get_credentials", return_value=None):
            result = runner.invoke(auth, ["show", "http://localhost:8000"])

            assert result.exit_code == 0
            assert "No credentials" in result.output

    def test_show_short_credentials_masked(self, runner):
        """Test that short credentials are fully masked."""
        mock_creds = create_bearer_auth("short")

        with patch("a2a_handler.cli.auth.get_credentials", return_value=mock_creds):
            result = runner.invoke(auth, ["show", "http://localhost:8000"])

            assert result.exit_code == 0
            assert "****" in result.output
            assert "short" not in result.output

    def test_show_rejects_invalid_agent_url(self, runner):
        """Test show fails early for malformed URL."""
        result = runner.invoke(auth, ["show", "not-a-url"])

        assert result.exit_code == 1
        assert "agent_url must be a valid http(s) URL" in result.output


class TestAuthClear:
    """Tests for auth clear command."""

    def test_clear_credentials(self, runner):
        """Test clearing credentials."""
        with patch("a2a_handler.cli.auth.clear_credentials") as mock_clear:
            result = runner.invoke(auth, ["clear", "http://localhost:8000"])

            assert result.exit_code == 0
            assert "Cleared" in result.output
            mock_clear.assert_called_once_with("http://localhost:8000")

    def test_clear_rejects_invalid_agent_url(self, runner):
        """Test clear fails early for malformed URL."""
        result = runner.invoke(auth, ["clear", "not-a-url"])

        assert result.exit_code == 1
        assert "agent_url must be a valid http(s) URL" in result.output


class TestAuthSource:
    """Tests for auth source command group."""

    def test_source_set_global_provider(self, runner):
        """Setting global auth source with built-in provider saves command."""
        with patch("a2a_handler.cli.auth.save_default_bearer_command") as mock_save:
            result = runner.invoke(auth, ["source", "set", "--provider", "gcloud"])

            assert result.exit_code == 0
            mock_save.assert_called_once_with("gcloud auth print-identity-token")
            assert "Set global auth source" in result.output

    def test_source_set_agent_command(self, runner):
        """Setting per-agent auth source stores command for that agent."""
        with patch("a2a_handler.cli.auth.save_agent_bearer_command") as mock_save:
            result = runner.invoke(
                auth,
                [
                    "source",
                    "set",
                    "http://localhost:8000",
                    "--command",
                    "gcloud auth print-identity-token",
                ],
            )

            assert result.exit_code == 0
            mock_save.assert_called_once_with(
                "http://localhost:8000",
                "gcloud auth print-identity-token",
            )

    def test_source_set_requires_provider_or_command(self, runner):
        """Auth source set requires one source mode."""
        result = runner.invoke(auth, ["source", "set"])

        assert result.exit_code == 1
        assert "Provide --provider or --command" in result.output

    def test_source_show_agent_falls_back_to_default(self, runner):
        """Agent source show falls back to configured global default."""
        with (
            patch("a2a_handler.cli.auth.get_agent_bearer_command", return_value=None),
            patch(
                "a2a_handler.cli.auth.get_default_bearer_command",
                return_value="gcloud auth print-identity-token",
            ),
        ):
            result = runner.invoke(auth, ["source", "show", "http://localhost:8000"])

            assert result.exit_code == 0
            assert "Default fallback" in result.output
            assert "gcloud auth print-identity-token" in result.output

    def test_source_clear_global(self, runner):
        """Clearing global source removes default bearer command."""
        with patch("a2a_handler.cli.auth.save_default_bearer_command") as mock_save:
            result = runner.invoke(auth, ["source", "clear"])

            assert result.exit_code == 0
            mock_save.assert_called_once_with(None)
            assert "Cleared global auth source" in result.output
