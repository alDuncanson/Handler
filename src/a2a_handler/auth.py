"""Authentication support for A2A protocol.

Handles credential storage and HTTP authentication header generation.
Supports API key, HTTP bearer, mTLS (mutual TLS), and OAuth2 client credentials
authentication schemes.
"""

from __future__ import annotations

import ssl
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


from a2a_handler.common.input_validation import (
    check_key_file_permissions,
    validate_header_name,
    validate_token_url,
)

import httpx


_TOKEN_EXPIRY_MARGIN = 30  # seconds before expiry to trigger refresh


class AuthType(str, Enum):
    """Supported authentication types."""

    API_KEY = "api_key"
    BEARER = "bearer"
    MTLS = "mtls"
    OAUTH2 = "oauth2"


@dataclass
class AuthCredentials:
    """Authentication credentials for an agent.

    Stores the credential value and metadata about how to apply it.
    """

    auth_type: AuthType
    value: str = ""
    header_name: str | None = None  # For API key: custom header name
    cert_path: str | None = None  # For mTLS: client certificate path
    key_path: str | None = None  # For mTLS: client private key path
    ca_cert_path: str | None = None  # For mTLS: CA certificate path
    token_url: str | None = None  # For OAuth2: token endpoint
    client_id: str | None = None  # For OAuth2: client ID
    client_secret: str | None = None  # For OAuth2: client secret
    scopes: list[str] | None = None  # For OAuth2: optional scopes
    custom_headers: dict[str, str] | None = None  # Additional headers for any auth type
    _token_expires_at: float | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        """Redacted repr to prevent secret leakage in logs and tracebacks."""
        redacted = {
            "auth_type": self.auth_type.value,
            "header_name": self.header_name,
            "cert_path": self.cert_path,
            "key_path": self.key_path,
            "ca_cert_path": self.ca_cert_path,
            "token_url": self.token_url,
        }
        for secret_field in ("value", "client_id", "client_secret"):
            val = getattr(self, secret_field)
            redacted[secret_field] = "***" if val else None
        if self.custom_headers:
            redacted["custom_headers"] = {k: "***" for k in self.custom_headers}
        return f"AuthCredentials({redacted})"

    def to_headers(self) -> dict[str, str]:
        """Generate HTTP headers for this credential.

        Returns:
            Dictionary of headers to include in requests
        """
        headers: dict[str, str] = {}
        if self.custom_headers:
            headers.update(self.custom_headers)
        if self.auth_type == AuthType.BEARER and self.value:
            headers["Authorization"] = f"Bearer {self.value}"
        elif self.auth_type == AuthType.OAUTH2 and self.value:
            headers["Authorization"] = f"Bearer {self.value}"
        elif self.auth_type == AuthType.API_KEY:
            header = self.header_name or "X-API-Key"
            headers[header] = self.value
        return headers

    def build_ssl_context(self) -> ssl.SSLContext:
        """Build an SSL context for mTLS client certificate authentication."""
        if self.auth_type != AuthType.MTLS:
            raise ValueError("SSL context can only be built for mTLS credentials")
        if not self.cert_path or not self.key_path:
            raise ValueError("cert_path and key_path are required for mTLS")

        if self.ca_cert_path:
            ctx = ssl.create_default_context(cafile=self.ca_cert_path)
        else:
            ctx = ssl.create_default_context()

        ctx.load_cert_chain(certfile=self.cert_path, keyfile=self.key_path)
        return ctx

    def is_token_expired(self) -> bool:
        """Check whether the cached OAuth2 access token has expired.

        Returns True when no token is present, when no expiry was recorded,
        or when the token will expire within a 30-second safety margin.
        """
        if not self.value:
            return True
        if self._token_expires_at is None:
            return True
        return time.monotonic() >= self._token_expires_at

    def clear_token(self) -> None:
        """Clear the cached OAuth2 access token so the next call re-fetches."""
        self.value = ""
        self._token_expires_at = None

    async def fetch_oauth2_token(self) -> str:
        """Fetch an access token using OAuth2 client credentials grant.

        Uses a short-lived HTTP client so that agent auth headers and custom
        headers on the main client are never sent to the token endpoint.

        Updates self.value with the new token and returns it.
        Parses ``expires_in`` from the token response to track expiry.
        """
        if self.auth_type != AuthType.OAUTH2:
            raise ValueError("Token fetch is only valid for OAuth2 credentials")
        if not self.token_url or not self.client_id or not self.client_secret:
            raise ValueError("token_url, client_id, and client_secret are required")
        validate_token_url(self.token_url)

        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.scopes:
            data["scope"] = " ".join(self.scopes)

        async with httpx.AsyncClient(trust_env=False) as token_client:
            response = await token_client.post(self.token_url, data=data)
        response.raise_for_status()
        token_data = response.json()
        self.value = token_data["access_token"]

        expires_in = token_data.get("expires_in")
        if isinstance(expires_in, (int, float)) and expires_in > 0:
            self._token_expires_at = (
                time.monotonic() + expires_in - _TOKEN_EXPIRY_MARGIN
            )
        else:
            self._token_expires_at = None

        return self.value

    def to_dict(self) -> dict:
        """Serialize credentials for storage."""
        data: dict = {
            "auth_type": self.auth_type.value,
            "value": self.value,
            "header_name": self.header_name,
        }
        if self.cert_path:
            data["cert_path"] = self.cert_path
        if self.key_path:
            data["key_path"] = self.key_path
        if self.ca_cert_path:
            data["ca_cert_path"] = self.ca_cert_path
        if self.token_url:
            data["token_url"] = self.token_url
        if self.client_id:
            data["client_id"] = self.client_id
        if self.client_secret:
            data["client_secret"] = self.client_secret
        if self.scopes:
            data["scopes"] = self.scopes
        if self.custom_headers:
            data["custom_headers"] = self.custom_headers
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "AuthCredentials":
        """Deserialize credentials from storage."""
        custom_headers_raw = data.get("custom_headers")
        custom_headers = (
            dict(custom_headers_raw) if isinstance(custom_headers_raw, dict) else None
        )
        return cls(
            auth_type=AuthType(data["auth_type"]),
            value=data.get("value") or "",
            header_name=data.get("header_name"),
            cert_path=data.get("cert_path"),
            key_path=data.get("key_path"),
            ca_cert_path=data.get("ca_cert_path"),
            token_url=data.get("token_url"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes"),
            custom_headers=custom_headers,
        )


def parse_header_string(header: str) -> tuple[str, str]:
    """Parse a 'Name: Value' header string into a (name, value) tuple."""
    if ":" not in header:
        raise ValueError(f"Invalid header format (expected 'Name: Value'): {header}")
    name, _, value = header.partition(":")
    name = name.strip()
    value = value.strip()
    if not name:
        raise ValueError(f"Empty header name in: {header}")
    validate_header_name(name, "custom_header")
    return name, value


def create_bearer_auth(token: str) -> AuthCredentials:
    """Create bearer token authentication."""
    return AuthCredentials(auth_type=AuthType.BEARER, value=token)


def create_api_key_auth(
    key: str,
    header_name: str = "X-API-Key",
) -> AuthCredentials:
    """Create API key authentication.

    Args:
        key: The API key value
        header_name: Header name to use (default: X-API-Key)
    """
    validate_header_name(header_name, "header_name")
    return AuthCredentials(
        auth_type=AuthType.API_KEY,
        value=key,
        header_name=header_name,
    )


def create_mtls_auth(
    cert_path: str,
    key_path: str,
    ca_cert_path: str | None = None,
) -> AuthCredentials:
    """Create mTLS (mutual TLS) client certificate authentication."""
    if not Path(cert_path).is_file():
        raise FileNotFoundError(f"Client certificate not found: {cert_path}")
    if not Path(key_path).is_file():
        raise FileNotFoundError(f"Client private key not found: {key_path}")
    if ca_cert_path and not Path(ca_cert_path).is_file():
        raise FileNotFoundError(f"CA certificate not found: {ca_cert_path}")
    check_key_file_permissions(key_path)

    return AuthCredentials(
        auth_type=AuthType.MTLS,
        cert_path=cert_path,
        key_path=key_path,
        ca_cert_path=ca_cert_path,
    )


def create_oauth2_auth(
    token_url: str,
    client_id: str,
    client_secret: str,
    scopes: list[str] | None = None,
    access_token: str = "",
) -> AuthCredentials:
    """Create OAuth2 client credentials authentication."""
    return AuthCredentials(
        auth_type=AuthType.OAUTH2,
        value=access_token,
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
    )
