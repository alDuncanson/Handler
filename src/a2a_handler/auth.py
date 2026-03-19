"""Authentication support for A2A protocol.

Handles credential storage and HTTP authentication header generation.
Supports API key, HTTP bearer, and mTLS (mutual TLS) authentication schemes.
"""

import ssl
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AuthType(str, Enum):
    """Supported authentication types."""

    API_KEY = "api_key"
    BEARER = "bearer"
    MTLS = "mtls"


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
    custom_headers: dict[str, str] | None = None  # Additional headers for any auth type

    def to_headers(self) -> dict[str, str]:
        """Generate HTTP headers for this credential.

        Returns:
            Dictionary of headers to include in requests
        """
        headers: dict[str, str] = {}
        if self.auth_type == AuthType.BEARER and self.value:
            headers["Authorization"] = f"Bearer {self.value}"
        elif self.auth_type == AuthType.API_KEY:
            header = self.header_name or "X-API-Key"
            headers[header] = self.value
        if self.custom_headers:
            headers.update(self.custom_headers)
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

    return AuthCredentials(
        auth_type=AuthType.MTLS,
        cert_path=cert_path,
        key_path=key_path,
        ca_cert_path=ca_cert_path,
    )
