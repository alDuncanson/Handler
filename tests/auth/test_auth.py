"""Tests for authentication module."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_api_key_auth,
    create_basic_auth,
    create_bearer_auth,
    create_mtls_auth,
    create_oauth2_auth,
    create_oidc_auth,
    parse_header_string,
)
from a2a_handler.common.input_validation import InputValidationError


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
        creds = create_api_key_auth("my-key", header_name="X-Custom-Key")
        assert creds.header_name == "X-Custom-Key"

    def test_create_api_key_auth_rejects_reserved_headers(self) -> None:
        """Reserved headers must not be usable for API key auth."""
        with pytest.raises(InputValidationError) as error:
            create_api_key_auth("my-key", header_name="Authorization")
        raised = error.value
        assert isinstance(raised, InputValidationError)
        assert raised.code == "reserved_header"


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

    def test_create_mtls_auth_expands_home_directory_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        cert_path = home / "client.pem"
        key_path = home / "client.key"
        ca_cert_path = home / "ca.pem"
        cert_path.write_text("cert")
        key_path.write_text("key")
        ca_cert_path.write_text("ca")

        import os

        os.chmod(key_path, 0o600)
        monkeypatch.setenv("HOME", str(home))

        creds = create_mtls_auth("~/client.pem", "~/client.key", "~/ca.pem")

        assert creds.cert_path == str(cert_path)
        assert creds.key_path == str(key_path)
        assert creds.ca_cert_path == str(ca_cert_path)

    def test_create_mtls_auth_rejects_insecure_key_permissions(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as cert_file:
            cert_path = cert_file.name
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as key_file:
            key_file.write(b"private-key")
            key_path = key_file.name

        try:
            import os

            os.chmod(key_path, 0o644)
            with pytest.raises(InputValidationError) as exc_info:
                create_mtls_auth(cert_path, key_path)
            assert isinstance(exc_info.value, InputValidationError)
            assert "readable by group or others" in exc_info.value.message
        finally:
            import os

            os.unlink(cert_path)
            os.unlink(key_path)

    def test_build_ssl_context_rejects_non_mtls(self) -> None:
        creds = AuthCredentials(auth_type=AuthType.BEARER, value="token")
        with pytest.raises(ValueError, match="mTLS"):
            creds.build_ssl_context()

    def test_build_ssl_context_requires_paths(self) -> None:
        creds = AuthCredentials(auth_type=AuthType.MTLS)
        with pytest.raises(ValueError, match="cert_path and key_path"):
            creds.build_ssl_context()


class TestBasicAuth:
    """Tests for HTTP basic authentication."""

    def test_basic_to_headers(self) -> None:
        """Basic auth encodes username:password as base64."""
        creds = create_basic_auth("alice", "secret")
        headers = creds.to_headers()
        # base64("alice:secret")
        assert headers == {"Authorization": "Basic YWxpY2U6c2VjcmV0"}

    def test_basic_allows_empty_password(self) -> None:
        """A username with an empty password still produces a header."""
        creds = create_basic_auth("alice", "")
        assert creds.to_headers() == {"Authorization": "Basic YWxpY2U6"}

    def test_basic_repr_redacts_username_and_password(self) -> None:
        """repr must not leak the username or password."""
        creds = create_basic_auth("alice", "hunter2-p4ss")
        rendered = repr(creds)
        assert "alice" not in rendered
        assert "hunter2-p4ss" not in rendered

    def test_basic_round_trips_through_dict(self) -> None:
        """to_dict/from_dict preserve basic auth fields."""
        creds = create_basic_auth("alice", "secret")
        restored = AuthCredentials.from_dict(creds.to_dict())
        assert restored.auth_type == AuthType.BASIC
        assert restored.username == "alice"
        assert restored.value == "secret"
        assert restored.to_headers() == creds.to_headers()


@pytest.mark.asyncio
class TestOIDCAuth:
    """Tests for OpenID Connect authentication."""

    def _discovery_response(self, token_endpoint: str | None):
        from unittest.mock import MagicMock

        response = MagicMock()
        document = {"issuer": "https://auth.example.com"}
        if token_endpoint:
            document["token_endpoint"] = token_endpoint
        response.json.return_value = document
        response.raise_for_status = MagicMock()
        return response

    async def test_discovery_resolves_token_endpoint(self) -> None:
        """Discovery fetches the well-known document and caches token_url."""
        from unittest.mock import patch

        creds = create_oidc_auth(
            "https://auth.example.com", "client-id", "client-secret"
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = self._discovery_response(
            "https://auth.example.com/oauth/token"
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("a2a_handler.auth.httpx.AsyncClient", return_value=mock_client):
            endpoint = await creds.discover_oidc_token_endpoint()

        assert endpoint == "https://auth.example.com/oauth/token"
        assert creds.token_url == "https://auth.example.com/oauth/token"
        mock_client.get.assert_called_once_with(
            "https://auth.example.com/.well-known/openid-configuration"
        )

    async def test_discovery_rejects_document_without_token_endpoint(self) -> None:
        """A discovery document with no token_endpoint fails clearly."""
        from unittest.mock import patch

        creds = create_oidc_auth(
            "https://auth.example.com", "client-id", "client-secret"
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = self._discovery_response(None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("a2a_handler.auth.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="no token_endpoint"):
                await creds.discover_oidc_token_endpoint()

    async def test_fetch_token_discovers_then_posts(self) -> None:
        """An OIDC token fetch discovers the endpoint, then runs the grant."""
        from unittest.mock import MagicMock, patch

        creds = create_oidc_auth(
            "https://auth.example.com",
            "client-id",
            "client-secret",
            scopes=["openid"],
        )

        token_response = MagicMock()
        token_response.json.return_value = {"access_token": "oidc-token-xyz"}
        token_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = self._discovery_response(
            "https://auth.example.com/oauth/token"
        )
        mock_client.post.return_value = token_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("a2a_handler.auth.httpx.AsyncClient", return_value=mock_client):
            token = await creds.fetch_oauth2_token()

        assert token == "oidc-token-xyz"
        assert creds.to_headers() == {"Authorization": "Bearer oidc-token-xyz"}
        mock_client.post.assert_called_once_with(
            "https://auth.example.com/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "scope": "openid",
            },
        )

    async def test_discovery_requires_oidc_credentials(self) -> None:
        """Discovery is refused for non-OIDC credential types."""
        creds = create_bearer_auth("token")
        with pytest.raises(ValueError, match="only valid for OIDC"):
            await creds.discover_oidc_token_endpoint()


class TestOAuth2Auth:
    def test_oauth2_to_headers_with_token(self) -> None:
        """OAuth2 with a fetched token generates Bearer header."""
        creds = AuthCredentials(
            auth_type=AuthType.OAUTH2,
            value="access-token-123",
            token_url="https://example.com/oauth/token",
            client_id="my-client",
            client_secret="my-secret",
        )
        headers = creds.to_headers()
        assert headers == {"Authorization": "Bearer access-token-123"}

    def test_oauth2_to_headers_without_token(self) -> None:
        """OAuth2 without a fetched token returns empty headers."""
        creds = AuthCredentials(
            auth_type=AuthType.OAUTH2,
            token_url="https://example.com/oauth/token",
            client_id="my-client",
            client_secret="my-secret",
        )
        headers = creds.to_headers()
        assert headers == {}

    def test_oauth2_to_dict_and_from_dict(self) -> None:
        """OAuth2 credentials round-trip through serialization."""
        original = AuthCredentials(
            auth_type=AuthType.OAUTH2,
            value="access-token",
            token_url="https://example.com/oauth/token",
            client_id="my-client",
            client_secret="my-secret",
            scopes=["read", "write"],
        )
        data = original.to_dict()
        restored = AuthCredentials.from_dict(data)

        assert restored.auth_type == AuthType.OAUTH2
        assert restored.value == "access-token"
        assert restored.token_url == "https://example.com/oauth/token"
        assert restored.client_id == "my-client"
        assert restored.client_secret == "my-secret"
        assert restored.scopes == ["read", "write"]

    def test_oauth2_to_dict_without_scopes(self) -> None:
        """OAuth2 without scopes omits scopes from dict."""
        creds = AuthCredentials(
            auth_type=AuthType.OAUTH2,
            token_url="https://example.com/oauth/token",
            client_id="my-client",
            client_secret="my-secret",
        )
        data = creds.to_dict()
        assert "scopes" not in data

    def test_create_oauth2_auth(self) -> None:
        """create_oauth2_auth creates correct credentials."""
        creds = create_oauth2_auth(
            "https://example.com/oauth/token",
            "my-client",
            "my-secret",
            scopes=["read"],
        )
        assert creds.auth_type == AuthType.OAUTH2
        assert creds.token_url == "https://example.com/oauth/token"
        assert creds.client_id == "my-client"
        assert creds.client_secret == "my-secret"
        assert creds.scopes == ["read"]
        assert creds.value == ""

    async def test_fetch_oauth2_token_rejects_non_oauth2(self) -> None:
        """fetch_oauth2_token rejects non-OAuth2 credentials."""
        creds = AuthCredentials(auth_type=AuthType.BEARER, value="token")
        with pytest.raises(ValueError, match="OAuth2"):
            await creds.fetch_oauth2_token()

    async def test_fetch_oauth2_token_success(self) -> None:
        """fetch_oauth2_token posts client credentials and stores token."""
        from unittest.mock import MagicMock, patch

        creds = create_oauth2_auth(
            "https://auth.example.com/oauth/token",
            "my-client-id",
            "my-client-secret",
            scopes=["read", "write"],
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "fetched-token-abc"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("a2a_handler.auth.httpx.AsyncClient", return_value=mock_client):
            token = await creds.fetch_oauth2_token()

        assert token == "fetched-token-abc"
        assert creds.value == "fetched-token-abc"
        assert creds.to_headers() == {"Authorization": "Bearer fetched-token-abc"}

        mock_client.post.assert_called_once_with(
            "https://auth.example.com/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "my-client-id",
                "client_secret": "my-client-secret",
                "scope": "read write",
            },
        )

    async def test_fetch_oauth2_token_without_scopes(self) -> None:
        """fetch_oauth2_token omits scope when no scopes configured."""
        from unittest.mock import MagicMock, patch

        creds = create_oauth2_auth(
            "https://auth.example.com/oauth/token",
            "my-client-id",
            "my-client-secret",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "token-no-scopes"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("a2a_handler.auth.httpx.AsyncClient", return_value=mock_client):
            await creds.fetch_oauth2_token()

        mock_client.post.assert_called_once_with(
            "https://auth.example.com/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "my-client-id",
                "client_secret": "my-client-secret",
            },
        )

    async def test_fetch_oauth2_token_http_error_propagates(self) -> None:
        """fetch_oauth2_token propagates HTTP errors from the token endpoint."""
        from unittest.mock import MagicMock, patch

        import httpx

        creds = create_oauth2_auth(
            "https://auth.example.com/oauth/token",
            "my-client-id",
            "my-client-secret",
        )
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("a2a_handler.auth.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await creds.fetch_oauth2_token()

    async def test_fetch_oauth2_token_missing_fields(self) -> None:
        """fetch_oauth2_token raises when OAuth2 fields are incomplete."""
        creds = AuthCredentials(
            auth_type=AuthType.OAUTH2,
            token_url="https://auth.example.com/oauth/token",
        )
        with pytest.raises(ValueError, match="token_url, client_id, and client_secret"):
            await creds.fetch_oauth2_token()

    async def test_fetch_oauth2_token_tracks_expiry(self) -> None:
        """fetch_oauth2_token parses expires_in and tracks expiry."""
        from unittest.mock import MagicMock, patch

        creds = create_oauth2_auth(
            "https://auth.example.com/oauth/token",
            "client-id",
            "client-secret",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "tok-1",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("a2a_handler.auth.httpx.AsyncClient", return_value=mock_client):
            await creds.fetch_oauth2_token()

        assert creds.value == "tok-1"
        assert creds._token_expires_at is not None
        assert not creds.is_token_expired()

    async def test_fetch_oauth2_token_without_expires_in(self) -> None:
        """Token without expires_in is treated as expired and refreshed per request."""
        from unittest.mock import MagicMock, patch

        creds = create_oauth2_auth(
            "https://auth.example.com/oauth/token",
            "client-id",
            "client-secret",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok-forever"}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("a2a_handler.auth.httpx.AsyncClient", return_value=mock_client):
            await creds.fetch_oauth2_token()

        assert creds.value == "tok-forever"
        assert creds._token_expires_at is None
        assert creds.is_token_expired()

    def test_is_token_expired_no_token(self) -> None:
        """Credentials with no token are considered expired."""
        creds = create_oauth2_auth(
            "https://auth.example.com/oauth/token", "cid", "csec"
        )
        assert creds.is_token_expired()

    def test_is_token_expired_past_expiry(self) -> None:
        """Token with an expiry in the past is expired."""
        import time

        creds = create_oauth2_auth(
            "https://auth.example.com/oauth/token", "cid", "csec"
        )
        creds.value = "tok-old"
        creds._token_expires_at = time.monotonic() - 10
        assert creds.is_token_expired()

    def test_is_token_expired_future_expiry(self) -> None:
        """Token with an expiry in the future is not expired."""
        import time

        creds = create_oauth2_auth(
            "https://auth.example.com/oauth/token", "cid", "csec"
        )
        creds.value = "tok-fresh"
        creds._token_expires_at = time.monotonic() + 3600
        assert not creds.is_token_expired()

    def test_clear_token_resets_value_and_expiry(self) -> None:
        """clear_token removes token and expiry."""
        import time

        creds = create_oauth2_auth(
            "https://auth.example.com/oauth/token", "cid", "csec"
        )
        creds.value = "tok-123"
        creds._token_expires_at = time.monotonic() + 3600

        creds.clear_token()

        assert creds.value == ""
        assert creds._token_expires_at is None
        assert creds.is_token_expired()


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
