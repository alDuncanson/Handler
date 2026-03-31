"""Tests for CLI helper functions."""

from unittest.mock import MagicMock, patch

import click
import httpx
import pytest
from a2a.client.errors import (
    A2AClientError,
    A2AClientHTTPError,
    A2AClientTimeoutError,
)

from a2a_handler.auth import AuthType
from a2a_handler.cli._helpers import (
    build_http_client,
    handle_client_error,
    resolve_agent_target,
    TIMEOUT,
)
from a2a_handler.common import Output
from a2a_handler.servers import (
    ServerAuthConfig,
    ServerCatalog,
    ServerDefinition,
    ServerSource,
)


class TestBuildHttpClient:
    """Tests for build_http_client function."""

    def test_returns_async_client(self):
        """Test that build_http_client returns an AsyncClient."""
        client = build_http_client()
        assert isinstance(client, httpx.AsyncClient)

    def test_default_timeout(self):
        """Test default timeout is applied."""
        client = build_http_client()
        assert client.timeout.connect == TIMEOUT
        assert client.timeout.read == TIMEOUT
        assert client.timeout.write == TIMEOUT

    def test_custom_timeout(self):
        """Test custom timeout is applied."""
        client = build_http_client(timeout=60)
        assert client.timeout.connect == 60
        assert client.timeout.read == 60


class TestHandleClientError:
    """Tests for handle_client_error function."""

    def test_timeout_error(self):
        """Test handling A2AClientTimeoutError."""
        output = MagicMock(spec=Output)
        error = A2AClientTimeoutError("Request timed out")

        handle_client_error(error, "http://localhost:8000", output)

        output.error.assert_called_once()
        assert output.error.call_args.kwargs["code"] == "request_timeout"
        call_args = output.error.call_args.kwargs["message"]
        assert "timed out" in call_args.lower()

    def test_http_error_connection(self):
        """Test handling A2AClientHTTPError with connection issue."""
        output = MagicMock(spec=Output)
        error = A2AClientHTTPError(500, "Connection refused")

        handle_client_error(error, "http://localhost:8000", output)

        output.error.assert_called_once()
        call_args = output.error.call_args.kwargs["message"]
        assert "Connection failed" in call_args or "Connection refused" in call_args

    def test_http_error_other(self):
        """Test handling A2AClientHTTPError with other issue."""
        output = MagicMock(spec=Output)
        error = A2AClientHTTPError(400, "Some HTTP error")

        handle_client_error(error, "http://localhost:8000", output)

        output.error.assert_called_once()
        call_args = output.error.call_args.kwargs["message"]
        assert "Some HTTP error" in call_args

    def test_generic_a2a_client_error(self):
        """Test handling generic A2AClientError."""
        output = MagicMock(spec=Output)
        error = A2AClientError("Generic A2A error")

        handle_client_error(error, "http://localhost:8000", output)

        output.error.assert_called_once()
        call_args = output.error.call_args.kwargs["message"]
        assert "Generic A2A error" in call_args

    def test_httpx_connect_error(self):
        """Test handling httpx.ConnectError."""
        output = MagicMock(spec=Output)
        error = httpx.ConnectError("Connection refused")

        handle_client_error(error, "http://localhost:8000", output)

        output.error.assert_called_once()
        call_args = output.error.call_args.kwargs["message"]
        assert "Connection refused" in call_args

    def test_httpx_timeout_error(self):
        """Test handling httpx.TimeoutException."""
        output = MagicMock(spec=Output)
        error = httpx.TimeoutException("Request timed out")

        handle_client_error(error, "http://localhost:8000", output)

        output.error.assert_called_once()
        call_args = output.error.call_args.kwargs["message"]
        assert "timed out" in call_args.lower()

    def test_httpx_status_error(self):
        """Test handling httpx.HTTPStatusError."""
        output = MagicMock(spec=Output)
        request = httpx.Request("GET", "http://localhost:8000")
        response = httpx.Response(404, text="Not Found", request=request)
        error = httpx.HTTPStatusError(
            "404 Not Found", request=request, response=response
        )

        handle_client_error(error, "http://localhost:8000", output)

        output.error.assert_called_once()
        call_args = output.error.call_args.kwargs["message"]
        assert "404" in call_args

    def test_generic_exception(self):
        """Test handling generic exceptions."""
        output = MagicMock(spec=Output)
        error = ValueError("Something went wrong")

        handle_client_error(error, "http://localhost:8000", output)

        output.error.assert_called_once()
        call_args = output.error.call_args.kwargs["message"]
        assert "Something went wrong" in call_args

    def test_no_output_falls_back_to_echo(self, capsys):
        """Test that when output is None, it falls back to click.echo."""
        error = ValueError("Error without output")

        handle_client_error(error, "http://localhost:8000", None)

        captured = capsys.readouterr()
        assert "Error without output" in captured.err


class TestResolveAgentTarget:
    """Tests for resolve_agent_target function."""

    def test_url_returns_url_directly(self):
        """Test that --url returns the URL directly."""
        url, creds = resolve_agent_target(url="http://localhost:8000", server=None)
        assert url == "http://localhost:8000"
        assert creds is None

    def test_url_with_bearer_returns_credentials(self):
        """Test that --url with --bearer returns bearer credentials."""
        url, creds = resolve_agent_target(
            url="http://localhost:8000",
            server=None,
            bearer_token="my-token",
        )
        assert url == "http://localhost:8000"
        assert creds is not None
        assert creds.auth_type == AuthType.BEARER

    def test_url_with_api_key_returns_credentials(self):
        """Test that --url with --api-key returns api key credentials."""
        url, creds = resolve_agent_target(
            url="http://localhost:8000",
            server=None,
            api_key="my-key",
        )
        assert url == "http://localhost:8000"
        assert creds is not None
        assert creds.auth_type == AuthType.API_KEY

    def test_server_resolves_from_catalog(self):
        """Test that --server resolves URL from server catalog."""
        server_def = ServerDefinition(
            server_id="global:handler_dev",
            source=ServerSource.GLOBAL,
            name="handler_dev",
            agent_url="http://localhost:8000",
        )
        catalog = ServerCatalog(global_servers=(server_def,))

        with patch(
            "a2a_handler.cli._helpers.load_server_catalog", return_value=catalog
        ):
            url, creds = resolve_agent_target(url=None, server="handler_dev")
            assert url == "http://localhost:8000"
            assert creds is None

    def test_server_with_auth_resolves_credentials(self):
        """Test that --server resolves credentials from server config."""
        server_def = ServerDefinition(
            server_id="global:handler_dev",
            source=ServerSource.GLOBAL,
            name="handler_dev",
            agent_url="http://localhost:8000",
            auth=ServerAuthConfig(
                auth_type=AuthType.BEARER,
                value="server-token",
            ),
        )
        catalog = ServerCatalog(global_servers=(server_def,))

        with patch(
            "a2a_handler.cli._helpers.load_server_catalog", return_value=catalog
        ):
            url, creds = resolve_agent_target(url=None, server="handler_dev")
            assert url == "http://localhost:8000"
            assert creds is not None
            assert creds.auth_type == AuthType.BEARER

    def test_server_with_cli_bearer_overrides_server_auth(self):
        """Test that CLI --bearer overrides server auth config."""
        server_def = ServerDefinition(
            server_id="global:handler_dev",
            source=ServerSource.GLOBAL,
            name="handler_dev",
            agent_url="http://localhost:8000",
            auth=ServerAuthConfig(
                auth_type=AuthType.BEARER,
                value="server-token",
            ),
        )
        catalog = ServerCatalog(global_servers=(server_def,))

        with patch(
            "a2a_handler.cli._helpers.load_server_catalog", return_value=catalog
        ):
            url, creds = resolve_agent_target(
                url=None, server="handler_dev", bearer_token="override-token"
            )
            assert url == "http://localhost:8000"
            assert creds is not None
            assert creds.value == "override-token"

    def test_server_not_found_raises_usage_error(self):
        """Test that unknown server name raises UsageError."""
        catalog = ServerCatalog()

        with (
            patch(
                "a2a_handler.cli._helpers.load_server_catalog", return_value=catalog
            ),
            pytest.raises(click.UsageError, match="not found"),
        ):
            resolve_agent_target(url=None, server="nonexistent")

    def test_neither_url_nor_server_raises_usage_error(self):
        """Test that missing both --url and --server raises UsageError."""
        with pytest.raises(click.UsageError, match="Provide --url or --server"):
            resolve_agent_target(url=None, server=None)

    def test_both_url_and_server_raises_usage_error(self):
        """Test that providing both --url and --server raises UsageError."""
        with pytest.raises(click.UsageError, match="not both"):
            resolve_agent_target(
                url="http://localhost:8000", server="handler_dev"
            )
