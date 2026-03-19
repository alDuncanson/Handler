"""Tests for CLI auth commands."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from a2a_handler.cli.auth import auth
from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_bearer_auth,
    create_api_key_auth,
)
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
        assert "only one auth method" in result.output.lower()

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


class TestAuthSetMTLS:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_set_mtls_credentials(self, runner):
        with (
            tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
            tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
        ):
            with patch("a2a_handler.cli.auth.set_credentials") as mock_set:
                result = runner.invoke(
                    auth,
                    [
                        "set",
                        "http://localhost:8000",
                        "--cert",
                        cert_file.name,
                        "--key",
                        key_file.name,
                    ],
                )

                assert result.exit_code == 0
                assert "mTLS" in result.output
                mock_set.assert_called_once()
                call_args = mock_set.call_args
                assert call_args[0][1].auth_type == AuthType.MTLS
                assert call_args[0][1].cert_path == cert_file.name
                assert call_args[0][1].key_path == key_file.name

    def test_set_mtls_with_ca_cert(self, runner):
        with (
            tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
            tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
            tempfile.NamedTemporaryFile(suffix=".pem") as ca_file,
        ):
            with patch("a2a_handler.cli.auth.set_credentials") as mock_set:
                result = runner.invoke(
                    auth,
                    [
                        "set",
                        "http://localhost:8000",
                        "--cert",
                        cert_file.name,
                        "--key",
                        key_file.name,
                        "--ca-cert",
                        ca_file.name,
                    ],
                )

                assert result.exit_code == 0
                call_args = mock_set.call_args
                assert call_args[0][1].ca_cert_path == ca_file.name

    def test_set_mtls_missing_key_fails(self, runner):
        with tempfile.NamedTemporaryFile(suffix=".pem") as cert_file:
            result = runner.invoke(
                auth,
                ["set", "http://localhost:8000", "--cert", cert_file.name],
            )
            assert result.exit_code == 1

    def test_set_mtls_missing_cert_fails(self, runner):
        with tempfile.NamedTemporaryFile(suffix=".pem") as key_file:
            result = runner.invoke(
                auth,
                ["set", "http://localhost:8000", "--key", key_file.name],
            )
            assert result.exit_code == 1

    def test_set_mtls_and_bearer_fails(self, runner):
        with (
            tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
            tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
        ):
            result = runner.invoke(
                auth,
                [
                    "set",
                    "http://localhost:8000",
                    "--cert",
                    cert_file.name,
                    "--key",
                    key_file.name,
                    "--bearer",
                    "token",
                ],
            )
            assert result.exit_code == 1

    def test_set_mtls_nonexistent_cert_fails(self, runner):
        with tempfile.NamedTemporaryFile(suffix=".pem") as key_file:
            result = runner.invoke(
                auth,
                [
                    "set",
                    "http://localhost:8000",
                    "--cert",
                    "/nonexistent/cert.pem",
                    "--key",
                    key_file.name,
                ],
            )
            assert result.exit_code == 1

    def test_show_mtls_credentials(self, runner):
        mock_creds = AuthCredentials(
            auth_type=AuthType.MTLS,
            cert_path="/path/to/cert.pem",
            key_path="/path/to/key.pem",
            ca_cert_path="/path/to/ca.pem",
        )

        with patch("a2a_handler.cli.auth.get_credentials", return_value=mock_creds):
            result = runner.invoke(auth, ["show", "http://localhost:8000"])

            assert result.exit_code == 0
            assert "mtls" in result.output.lower()
            assert "/path/to/cert.pem" in result.output
            assert "/path/to/key.pem" in result.output
            assert "/path/to/ca.pem" in result.output


class TestAuthSetCustomHeaders:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_set_bearer_with_custom_headers(self, runner):
        with patch("a2a_handler.cli.auth.set_credentials") as mock_set:
            result = runner.invoke(
                auth,
                [
                    "set",
                    "http://localhost:8000",
                    "--bearer",
                    "my-token",
                    "--header",
                    "x-user-id: me@example.com",
                ],
            )

            assert result.exit_code == 0
            assert "x-user-id" in result.output
            call_args = mock_set.call_args
            creds = call_args[0][1]
            assert creds.auth_type == AuthType.BEARER
            assert creds.custom_headers == {"x-user-id": "me@example.com"}

    def test_set_multiple_custom_headers(self, runner):
        with patch("a2a_handler.cli.auth.set_credentials") as mock_set:
            result = runner.invoke(
                auth,
                [
                    "set",
                    "http://localhost:8000",
                    "--bearer",
                    "my-token",
                    "-H",
                    "x-user-id: me@example.com",
                    "-H",
                    "x-org: acme",
                ],
            )

            assert result.exit_code == 0
            creds = mock_set.call_args[0][1]
            assert creds.custom_headers == {
                "x-user-id": "me@example.com",
                "x-org": "acme",
            }

    def test_set_headers_only(self, runner):
        with patch("a2a_handler.cli.auth.set_credentials") as mock_set:
            result = runner.invoke(
                auth,
                [
                    "set",
                    "http://localhost:8000",
                    "--header",
                    "x-user-id: me@example.com",
                ],
            )

            assert result.exit_code == 0
            creds = mock_set.call_args[0][1]
            assert creds.custom_headers == {"x-user-id": "me@example.com"}

    def test_set_invalid_header_format_fails(self, runner):
        result = runner.invoke(
            auth,
            [
                "set",
                "http://localhost:8000",
                "--bearer",
                "token",
                "--header",
                "no-colon-here",
            ],
        )
        assert result.exit_code == 1

    def test_show_custom_headers(self, runner):
        mock_creds = AuthCredentials(
            auth_type=AuthType.BEARER,
            value="my-token-value-here",
            custom_headers={"x-user-id": "me@example.com"},
        )

        with patch("a2a_handler.cli.auth.get_credentials", return_value=mock_creds):
            result = runner.invoke(auth, ["show", "http://localhost:8000"])

            assert result.exit_code == 0
            assert "x-user-id" in result.output
            assert "me@example.com" in result.output
