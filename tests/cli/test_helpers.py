"""Tests for CLI helper functions."""

import os
from unittest.mock import MagicMock, patch

import click
import httpx
import pytest
from a2a.client.errors import (
    A2AClientError,
    A2AClientTimeoutError,
    AgentCardResolutionError,
)

from a2a_handler.auth import AuthType
from a2a_handler.cli._helpers import (
    AgentSelection,
    build_http_client,
    build_streaming_http_client,
    configure_http_timeouts,
    handle_client_error,
    TIMEOUT,
    resolve_agent_selection,
    resolve_selection_credentials,
    resolve_agent_target,
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

    def test_streaming_timeout_disables_read_timeout(self):
        """Test streaming clients keep finite setup timeouts but no read timeout."""
        client = build_streaming_http_client()
        assert client.timeout.connect == TIMEOUT
        assert client.timeout.read is None
        assert client.timeout.write == TIMEOUT
        assert client.timeout.pool == TIMEOUT

    def test_configured_timeouts_apply_to_standard_and_streaming_clients(self):
        """Test configured timeout knobs are used by HTTP clients."""
        configure_http_timeouts(
            connect_timeout="5",
            read_timeout="6",
            write_timeout="7",
            pool_timeout="8",
            stream_read_timeout="9",
        )

        standard_client = build_http_client()
        assert standard_client.timeout.connect == 5
        assert standard_client.timeout.read == 6
        assert standard_client.timeout.write == 7
        assert standard_client.timeout.pool == 8

        streaming_client = build_streaming_http_client()
        assert streaming_client.timeout.connect == 5
        assert streaming_client.timeout.read == 9
        assert streaming_client.timeout.write == 7
        assert streaming_client.timeout.pool == 8

    def test_timeout_none_value_disables_timeout(self):
        """Test 'none' disables a configured timeout."""
        configure_http_timeouts(read_timeout="none", stream_read_timeout="30")

        standard_client = build_http_client()
        assert standard_client.timeout.read is None

        streaming_client = build_streaming_http_client()
        assert streaming_client.timeout.read == 30

    def test_invalid_timeout_value_raises_click_error(self):
        """Test invalid timeout values are rejected."""
        with pytest.raises(click.BadParameter):
            configure_http_timeouts(connect_timeout="not-a-number")


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

    def test_agent_card_resolution_error_connection(self):
        """Test handling AgentCardResolutionError carrying a connection issue.

        v1.0 removed ``A2AClientHTTPError``; HTTP-level failures resolving the
        agent now surface as ``AgentCardResolutionError`` (with a status code).
        """
        output = MagicMock(spec=Output)
        error = AgentCardResolutionError("Connection refused", status_code=500)

        handle_client_error(error, "http://localhost:8000", output)

        output.error.assert_called_once()
        assert output.error.call_args.kwargs["code"] == "agent_card_resolution_error"
        call_args = output.error.call_args.kwargs["message"]
        assert "Connection refused" in call_args

    def test_agent_card_resolution_error_other(self):
        """Test handling AgentCardResolutionError with a non-connection issue."""
        output = MagicMock(spec=Output)
        error = AgentCardResolutionError("Some HTTP error", status_code=400)

        handle_client_error(error, "http://localhost:8000", output)

        output.error.assert_called_once()
        assert output.error.call_args.kwargs["code"] == "agent_card_resolution_error"
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

    def test_selection_resolves_url_without_credentials(self):
        """The clean selection helper only resolves the URL and server metadata."""
        selection = resolve_agent_selection(url="http://localhost:8000", server=None)
        assert selection.agent_url == "http://localhost:8000"
        assert selection.server_def is None

    def test_url_with_bearer_env_returns_credentials(self):
        """Test that --url with --bearer-env returns bearer credentials."""
        with patch.dict(os.environ, {"TEST_BEARER": "my-token"}):
            url, creds = resolve_agent_target(
                url="http://localhost:8000",
                server=None,
                bearer_env="TEST_BEARER",
            )
        assert url == "http://localhost:8000"
        assert creds is not None
        assert creds.auth_type == AuthType.BEARER

    def test_url_with_api_key_env_returns_credentials(self):
        """Test that --url with --api-key-env returns api key credentials."""
        with patch.dict(os.environ, {"TEST_API_KEY": "my-key"}):
            url, creds = resolve_agent_target(
                url="http://localhost:8000",
                server=None,
                api_key_env="TEST_API_KEY",
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

    def test_server_with_cli_bearer_env_overrides_server_auth(self):
        """Test that CLI --bearer-env overrides server auth config."""
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

        with (
            patch("a2a_handler.cli._helpers.load_server_catalog", return_value=catalog),
            patch.dict(os.environ, {"OVERRIDE_TOKEN": "override-token"}),
        ):
            url, creds = resolve_agent_target(
                url=None, server="handler_dev", bearer_env="OVERRIDE_TOKEN"
            )
            assert url == "http://localhost:8000"
            assert creds is not None
            assert creds.value == "override-token"

    def test_selection_credentials_fail_closed_when_server_auth_unavailable(self):
        """Named-server auth problems should stop the request instead of downgrading."""
        server_def = ServerDefinition(
            server_id="global:handler_dev",
            source=ServerSource.GLOBAL,
            name="handler_dev",
            agent_url="http://localhost:8000",
            auth=ServerAuthConfig(
                auth_type=AuthType.BEARER,
                env_var="MISSING_TOKEN",
            ),
        )
        selection = AgentSelection(
            agent_url=server_def.agent_url,
            server_def=server_def,
        )

        with pytest.raises(click.UsageError, match="MISSING_TOKEN"):
            resolve_selection_credentials(selection)

    def test_server_name_collision_raises_usage_error(self):
        """Duplicate server names across sources must fail closed."""
        repo_server = ServerDefinition(
            server_id="repository:shared",
            source=ServerSource.REPOSITORY,
            name="shared",
            agent_url="https://repo.example.com",
        )
        global_server = ServerDefinition(
            server_id="global:shared",
            source=ServerSource.GLOBAL,
            name="shared",
            agent_url="https://global.example.com",
        )
        catalog = ServerCatalog(
            repository_servers=(repo_server,),
            global_servers=(global_server,),
        )

        with (
            patch("a2a_handler.cli._helpers.load_server_catalog", return_value=catalog),
            pytest.raises(click.UsageError, match="multiple sources"),
        ):
            resolve_agent_target(url=None, server="shared")

    def test_server_not_found_raises_usage_error(self):
        """Test that unknown server name raises UsageError."""
        catalog = ServerCatalog()

        with (
            patch("a2a_handler.cli._helpers.load_server_catalog", return_value=catalog),
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
            resolve_agent_target(url="http://localhost:8000", server="handler_dev")
