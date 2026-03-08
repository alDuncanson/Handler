"""Tests for CLI helper functions."""

from unittest.mock import MagicMock

import httpx
from a2a.client.errors import (
    A2AClientError,
    A2AClientHTTPError,
    A2AClientTimeoutError,
)

from a2a_handler.cli._helpers import build_http_client, handle_client_error, TIMEOUT
from a2a_handler.common import Output


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

        output.error_obj.assert_called_once()
        assert output.error_obj.call_args.kwargs["code"] == "request_timeout"
        call_args = output.error_obj.call_args.kwargs["message"]
        assert "timed out" in call_args.lower()

    def test_http_error_connection(self):
        """Test handling A2AClientHTTPError with connection issue."""
        output = MagicMock(spec=Output)
        error = A2AClientHTTPError(500, "Connection refused")

        handle_client_error(error, "http://localhost:8000", output)

        output.error_obj.assert_called_once()
        call_args = output.error_obj.call_args.kwargs["message"]
        assert "Connection failed" in call_args or "Connection refused" in call_args

    def test_http_error_other(self):
        """Test handling A2AClientHTTPError with other issue."""
        output = MagicMock(spec=Output)
        error = A2AClientHTTPError(400, "Some HTTP error")

        handle_client_error(error, "http://localhost:8000", output)

        output.error_obj.assert_called_once()
        call_args = output.error_obj.call_args.kwargs["message"]
        assert "Some HTTP error" in call_args

    def test_generic_a2a_client_error(self):
        """Test handling generic A2AClientError."""
        output = MagicMock(spec=Output)
        error = A2AClientError("Generic A2A error")

        handle_client_error(error, "http://localhost:8000", output)

        output.error_obj.assert_called_once()
        call_args = output.error_obj.call_args.kwargs["message"]
        assert "Generic A2A error" in call_args

    def test_httpx_connect_error(self):
        """Test handling httpx.ConnectError."""
        output = MagicMock(spec=Output)
        error = httpx.ConnectError("Connection refused")

        handle_client_error(error, "http://localhost:8000", output)

        output.error_obj.assert_called_once()
        call_args = output.error_obj.call_args.kwargs["message"]
        assert "Connection refused" in call_args

    def test_httpx_timeout_error(self):
        """Test handling httpx.TimeoutException."""
        output = MagicMock(spec=Output)
        error = httpx.TimeoutException("Request timed out")

        handle_client_error(error, "http://localhost:8000", output)

        output.error_obj.assert_called_once()
        call_args = output.error_obj.call_args.kwargs["message"]
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

        output.error_obj.assert_called_once()
        call_args = output.error_obj.call_args.kwargs["message"]
        assert "404" in call_args

    def test_generic_exception(self):
        """Test handling generic exceptions."""
        output = MagicMock(spec=Output)
        error = ValueError("Something went wrong")

        handle_client_error(error, "http://localhost:8000", output)

        output.error_obj.assert_called_once()
        call_args = output.error_obj.call_args.kwargs["message"]
        assert "Something went wrong" in call_args

    def test_no_output_falls_back_to_echo(self, capsys):
        """Test that when output is None, it falls back to click.echo."""
        error = ValueError("Error without output")

        handle_client_error(error, "http://localhost:8000", None)

        captured = capsys.readouterr()
        assert "Error without output" in captured.err
