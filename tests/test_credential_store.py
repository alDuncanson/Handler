"""Tests for the separated credential store."""

import os
import stat
import tempfile
from pathlib import Path

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.credential_store import CredentialStore


def test_save_and_load_mtls_credentials() -> None:
    with tempfile.TemporaryDirectory() as temp_directory:
        store = CredentialStore(credential_directory=Path(temp_directory))
        mtls_creds = AuthCredentials(
            auth_type=AuthType.MTLS,
            cert_path="/path/to/cert.pem",
            key_path="/path/to/key.pem",
            ca_cert_path="/path/to/ca.pem",
        )
        store.set("http://localhost:8000", mtls_creds)

        new_store = CredentialStore(credential_directory=Path(temp_directory))
        new_store.load()

        loaded_creds = new_store.get("http://localhost:8000")
        assert loaded_creds is not None
        assert loaded_creds.auth_type == AuthType.MTLS
        assert loaded_creds.cert_path == "/path/to/cert.pem"
        assert loaded_creds.key_path == "/path/to/key.pem"
        assert loaded_creds.ca_cert_path == "/path/to/ca.pem"


def test_save_and_load_custom_headers() -> None:
    with tempfile.TemporaryDirectory() as temp_directory:
        store = CredentialStore(credential_directory=Path(temp_directory))
        creds = AuthCredentials(
            auth_type=AuthType.BEARER,
            value="token",
            custom_headers={"x-user-id": "me@example.com", "x-org": "acme"},
        )
        store.set("http://localhost:8000", creds)

        new_store = CredentialStore(credential_directory=Path(temp_directory))
        new_store.load()

        loaded_creds = new_store.get("http://localhost:8000")
        assert loaded_creds is not None
        assert loaded_creds.custom_headers == {
            "x-user-id": "me@example.com",
            "x-org": "acme",
        }


def test_clear_removes_saved_credentials() -> None:
    with tempfile.TemporaryDirectory() as temp_directory:
        store = CredentialStore(credential_directory=Path(temp_directory))
        store.set(
            "http://localhost:8000",
            AuthCredentials(auth_type=AuthType.BEARER, value="token"),
        )

        store.clear("http://localhost:8000")

        assert store.get("http://localhost:8000") is None


def test_save_sets_owner_only_permissions() -> None:
    with tempfile.TemporaryDirectory() as temp_directory:
        store = CredentialStore(credential_directory=Path(temp_directory))
        store.set(
            "http://localhost:8000",
            AuthCredentials(auth_type=AuthType.BEARER, value="token"),
        )

        file_stat = os.stat(store.credential_file_path)
        file_mode = stat.S_IMODE(file_stat.st_mode)
        assert file_mode == 0o600
