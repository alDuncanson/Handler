"""Tests for authentication module."""

import tempfile

import pytest

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_api_key_auth,
    create_bearer_auth,
    create_mtls_auth,
    parse_header_string,
)


class TestAuthCredentials:
    """Tests for AuthCredentials class."""

    def test_bearer_to_headers(self) -> None:
        """Bearer token generates Authorization header."""
        creds = AuthCredentials(auth_type=AuthType.BEARER, value="my-secret-token")
        headers = creds.to_headers()
        assert headers == {"Authorization": "Bearer my-secret-token"}

    def test_api_key_to_headers_default(self) -> None:
        """API key uses default X-API-Key header."""
        creds = AuthCredentials(auth_type=AuthType.API_KEY, value="my-api-key")
        headers = creds.to_headers()
        assert headers == {"X-API-Key": "my-api-key"}

    def test_api_key_to_headers_custom(self) -> None:
        """API key uses custom header name."""
        creds = AuthCredentials(
            auth_type=AuthType.API_KEY,
            value="my-api-key",
            header_name="X-Custom-Key",
        )
        headers = creds.to_headers()
        assert headers == {"X-Custom-Key": "my-api-key"}

    def test_to_dict_and_from_dict_bearer(self) -> None:
        """Bearer credentials round-trip through serialization."""
        original = AuthCredentials(auth_type=AuthType.BEARER, value="token123")
        data = original.to_dict()
        restored = AuthCredentials.from_dict(data)

        assert restored.auth_type == original.auth_type
        assert restored.value == original.value

    def test_to_dict_and_from_dict_api_key(self) -> None:
        """API key credentials round-trip through serialization."""
        original = AuthCredentials(
            auth_type=AuthType.API_KEY,
            value="key123",
            header_name="X-My-Key",
        )
        data = original.to_dict()
        restored = AuthCredentials.from_dict(data)

        assert restored.auth_type == original.auth_type
        assert restored.value == original.value
        assert restored.header_name == original.header_name


class TestAuthHelpers:
    """Tests for auth helper functions."""

    def test_create_bearer_auth(self) -> None:
        """create_bearer_auth creates correct credentials."""
        creds = create_bearer_auth("my-token")
        assert creds.auth_type == AuthType.BEARER
        assert creds.value == "my-token"

    def test_create_api_key_auth_default(self) -> None:
        """create_api_key_auth with defaults."""
        creds = create_api_key_auth("my-key")
        assert creds.auth_type == AuthType.API_KEY
        assert creds.value == "my-key"
        assert creds.header_name == "X-API-Key"

    def test_create_api_key_auth_custom(self) -> None:
        """create_api_key_auth with custom header."""
        creds = create_api_key_auth("my-key", header_name="Authorization")
        assert creds.header_name == "Authorization"


class TestMTLSAuth:
    def test_mtls_to_headers_returns_empty(self) -> None:
        creds = AuthCredentials(
            auth_type=AuthType.MTLS,
            cert_path="/tmp/cert.pem",
            key_path="/tmp/key.pem",
        )
        assert creds.to_headers() == {}

    def test_mtls_to_dict_and_from_dict(self) -> None:
        original = AuthCredentials(
            auth_type=AuthType.MTLS,
            cert_path="/tmp/cert.pem",
            key_path="/tmp/key.pem",
            ca_cert_path="/tmp/ca.pem",
        )
        data = original.to_dict()
        restored = AuthCredentials.from_dict(data)

        assert restored.auth_type == AuthType.MTLS
        assert restored.cert_path == "/tmp/cert.pem"
        assert restored.key_path == "/tmp/key.pem"
        assert restored.ca_cert_path == "/tmp/ca.pem"

    def test_mtls_to_dict_without_ca_cert(self) -> None:
        creds = AuthCredentials(
            auth_type=AuthType.MTLS,
            cert_path="/tmp/cert.pem",
            key_path="/tmp/key.pem",
        )
        data = creds.to_dict()
        assert "ca_cert_path" not in data

    def test_create_mtls_auth_validates_cert_exists(self) -> None:
        with pytest.raises(FileNotFoundError, match="Client certificate not found"):
            create_mtls_auth("/nonexistent/cert.pem", "/nonexistent/key.pem")

    def test_create_mtls_auth_validates_key_exists(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pem") as cert_file:
            with pytest.raises(FileNotFoundError, match="Client private key not found"):
                create_mtls_auth(cert_file.name, "/nonexistent/key.pem")

    def test_create_mtls_auth_validates_ca_cert_exists(self) -> None:
        with (
            tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
            tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
        ):
            with pytest.raises(FileNotFoundError, match="CA certificate not found"):
                create_mtls_auth(cert_file.name, key_file.name, "/nonexistent/ca.pem")

    def test_create_mtls_auth_success(self) -> None:
        with (
            tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
            tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
        ):
            creds = create_mtls_auth(cert_file.name, key_file.name)
            assert creds.auth_type == AuthType.MTLS
            assert creds.cert_path == cert_file.name
            assert creds.key_path == key_file.name
            assert creds.ca_cert_path is None

    def test_create_mtls_auth_with_ca_cert(self) -> None:
        with (
            tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
            tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
            tempfile.NamedTemporaryFile(suffix=".pem") as ca_file,
        ):
            creds = create_mtls_auth(cert_file.name, key_file.name, ca_file.name)
            assert creds.ca_cert_path == ca_file.name

    def test_build_ssl_context_rejects_non_mtls(self) -> None:
        creds = AuthCredentials(auth_type=AuthType.BEARER, value="token")
        with pytest.raises(ValueError, match="mTLS"):
            creds.build_ssl_context()

    def test_build_ssl_context_requires_paths(self) -> None:
        creds = AuthCredentials(auth_type=AuthType.MTLS)
        with pytest.raises(ValueError, match="cert_path and key_path"):
            creds.build_ssl_context()


class TestCustomHeaders:
    def test_custom_headers_merged_with_bearer(self) -> None:
        creds = AuthCredentials(
            auth_type=AuthType.BEARER,
            value="token",
            custom_headers={"x-user-id": "me@example.com"},
        )
        headers = creds.to_headers()
        assert headers["Authorization"] == "Bearer token"
        assert headers["x-user-id"] == "me@example.com"

    def test_custom_headers_merged_with_api_key(self) -> None:
        creds = AuthCredentials(
            auth_type=AuthType.API_KEY,
            value="key123",
            custom_headers={"x-org": "acme"},
        )
        headers = creds.to_headers()
        assert headers["X-API-Key"] == "key123"
        assert headers["x-org"] == "acme"

    def test_custom_headers_with_mtls(self) -> None:
        creds = AuthCredentials(
            auth_type=AuthType.MTLS,
            cert_path="/tmp/cert.pem",
            key_path="/tmp/key.pem",
            custom_headers={"x-user-id": "me@example.com"},
        )
        headers = creds.to_headers()
        assert headers == {"x-user-id": "me@example.com"}

    def test_custom_headers_only(self) -> None:
        creds = AuthCredentials(
            auth_type=AuthType.BEARER,
            custom_headers={"x-user-id": "me@example.com", "x-org": "acme"},
        )
        headers = creds.to_headers()
        assert "Authorization" not in headers
        assert headers == {"x-user-id": "me@example.com", "x-org": "acme"}

    def test_custom_headers_roundtrip_serialization(self) -> None:
        original = AuthCredentials(
            auth_type=AuthType.BEARER,
            value="token",
            custom_headers={"x-user-id": "me@example.com", "x-org": "acme"},
        )
        data = original.to_dict()
        restored = AuthCredentials.from_dict(data)

        assert restored.custom_headers == {
            "x-user-id": "me@example.com",
            "x-org": "acme",
        }

    def test_no_custom_headers_not_in_dict(self) -> None:
        creds = AuthCredentials(auth_type=AuthType.BEARER, value="token")
        data = creds.to_dict()
        assert "custom_headers" not in data


class TestParseHeaderString:
    def test_parse_valid_header(self) -> None:
        name, value = parse_header_string("x-user-id: me@example.com")
        assert name == "x-user-id"
        assert value == "me@example.com"

    def test_parse_header_with_extra_colons(self) -> None:
        name, value = parse_header_string("x-data: value:with:colons")
        assert name == "x-data"
        assert value == "value:with:colons"

    def test_parse_header_strips_whitespace(self) -> None:
        name, value = parse_header_string("  x-user-id  :  me@example.com  ")
        assert name == "x-user-id"
        assert value == "me@example.com"

    def test_parse_header_no_colon_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid header format"):
            parse_header_string("no-colon-here")

    def test_parse_header_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty header name"):
            parse_header_string(": value")
