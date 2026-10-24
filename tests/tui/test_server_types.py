"""Tests for shared server types and helpers."""

from __future__ import annotations

import ssl
import tempfile
from unittest.mock import patch

import httpx

from a2a_handler.auth import AuthCredentials, create_bearer_auth, create_mtls_auth
from a2a_handler.tui.server.types import (
    SHORT_ID_LENGTH,
    build_http_client,
    summarize_identifier,
)


def test_summarize_identifier_keeps_short_ids() -> None:
    assert summarize_identifier("abc") == "abc"
    exact = "x" * SHORT_ID_LENGTH
    assert summarize_identifier(exact) == exact


def test_summarize_identifier_truncates_long_ids() -> None:
    assert summarize_identifier("0123456789abcdef") == "0123456789ab..."


async def test_build_http_client_uses_the_mtls_context() -> None:
    with (
        tempfile.NamedTemporaryFile(suffix=".pem") as cert_file,
        tempfile.NamedTemporaryFile(suffix=".pem") as key_file,
    ):
        creds = create_mtls_auth(cert_file.name, key_file.name)
    context = ssl.create_default_context()
    with patch.object(
        AuthCredentials, "build_ssl_context", return_value=context
    ) as build:
        client = build_http_client(credentials=creds)
    build.assert_called_once_with()
    assert isinstance(client, httpx.AsyncClient)
    await client.aclose()


async def test_build_http_client_without_mtls_skips_the_ssl_context() -> None:
    with patch.object(AuthCredentials, "build_ssl_context") as build:
        client = build_http_client(credentials=create_bearer_auth("token"))
    build.assert_not_called()
    assert isinstance(client, httpx.AsyncClient)
    await client.aclose()
