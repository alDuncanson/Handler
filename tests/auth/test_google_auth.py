"""Tests for Google Cloud (OIDC ID token / IAP / ADC) auth and card auto-detect."""

from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace

import pytest

import a2a.types as a2a_types
from a2a_handler.auth import AuthCredentials, AuthType, create_google_auth
from a2a_handler.server.card import build_agent_card
from a2a_handler.service import recommend_auth_from_card


def _make_jwt(exp: int) -> str:
    """Build an unsigned JWT carrying only an ``exp`` claim."""

    def seg(payload: dict) -> str:
        raw = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{seg({'alg': 'RS256'})}.{seg({'exp': exp})}.sig"


class TestCreateGoogleAuth:
    def test_adc_default(self) -> None:
        creds = create_google_auth(audience="https://x.run.app")
        assert creds.auth_type == AuthType.GOOGLE
        assert creds.credential_source == "adc"
        assert creds.audience == "https://x.run.app"

    def test_invalid_source_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid credential_source"):
            create_google_auth(credential_source="bogus")

    def test_service_account_requires_file(self) -> None:
        with pytest.raises(ValueError, match="service_account_file is required"):
            create_google_auth(credential_source="service_account")

    def test_service_account_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            create_google_auth(
                credential_source="service_account",
                service_account_file="/nonexistent/sa.json",
            )

    def test_impersonate_requires_target(self) -> None:
        with pytest.raises(ValueError, match="impersonate_service_account is required"):
            create_google_auth(credential_source="impersonate")


class TestGoogleHeadersAndSerialization:
    def test_to_headers_only_with_token(self) -> None:
        creds = create_google_auth(audience="https://x")
        assert creds.to_headers() == {}
        creds.value = "id-token-value"
        assert creds.to_headers() == {"Authorization": "Bearer id-token-value"}

    def test_repr_redacts_token(self) -> None:
        creds = create_google_auth(audience="https://x")
        creds.value = "supersecret-token"
        assert "supersecret-token" not in repr(creds)

    def test_to_dict_omits_ephemeral_token(self) -> None:
        creds = create_google_auth(audience="https://x", credential_source="adc")
        creds.value = "id-token-value"
        data = creds.to_dict()

        assert data["value"] == ""  # minted token never persisted
        assert data["audience"] == "https://x"
        assert data["credential_source"] == "adc"

        restored = AuthCredentials.from_dict(data)
        assert restored.auth_type == AuthType.GOOGLE
        assert restored.audience == "https://x"
        assert restored.value == ""

    def test_to_dict_roundtrips_impersonate(self) -> None:
        creds = create_google_auth(
            audience="https://x",
            credential_source="impersonate",
            impersonate_service_account="deployer@proj.iam.gserviceaccount.com",
        )
        restored = AuthCredentials.from_dict(creds.to_dict())
        assert restored.credential_source == "impersonate"
        assert (
            restored.impersonate_service_account
            == "deployer@proj.iam.gserviceaccount.com"
        )


class TestFetchGoogleIdToken:
    async def test_fetch_sets_value_and_expiry(self, monkeypatch) -> None:
        creds = create_google_auth(audience="https://x")
        expires_at = int(time.time()) + 3600
        token = _make_jwt(expires_at)
        monkeypatch.setattr(creds, "_mint_google_id_token", lambda: token)

        result = await creds.fetch_google_id_token()

        assert result == token
        assert creds.value == token
        assert not creds.is_token_expired()

    async def test_fetch_requires_audience(self) -> None:
        creds = create_google_auth()  # no audience
        with pytest.raises(ValueError, match="audience is required"):
            await creds.fetch_google_id_token()

    def test_expiry_decode_handles_garbage(self) -> None:
        assert AuthCredentials._google_token_expiry("not-a-jwt") is None

    def test_expiry_decode_past_token(self) -> None:
        past = int(time.time()) - 10
        assert AuthCredentials._google_token_expiry(_make_jwt(past)) is None


class TestRecommendAuthFromCard:
    def test_api_key_card(self) -> None:
        card = build_agent_card(
            SimpleNamespace(name="H", description="d"),
            "0.0.0.0",
            8000,
            require_auth=True,
        )
        recommendation = recommend_auth_from_card(card)
        assert recommendation is not None
        assert recommendation.auth_type == AuthType.API_KEY
        assert recommendation.header_name == "X-API-Key"

    def test_no_requirement_returns_none(self) -> None:
        card = build_agent_card(
            SimpleNamespace(name="H", description="d"),
            "0.0.0.0",
            8000,
            require_auth=False,
        )
        assert recommend_auth_from_card(card) is None

    def test_http_bearer_card(self) -> None:
        scheme = a2a_types.SecurityScheme(
            http_auth_security_scheme=a2a_types.HTTPAuthSecurityScheme(scheme="bearer")
        )
        card = a2a_types.AgentCard(
            name="B",
            security_schemes={"bearerAuth": scheme},
            security_requirements=[
                a2a_types.SecurityRequirement(
                    schemes={"bearerAuth": a2a_types.StringList()}
                )
            ],
        )
        recommendation = recommend_auth_from_card(card)
        assert recommendation is not None
        assert recommendation.auth_type == AuthType.BEARER

    def test_mtls_card(self) -> None:
        scheme = a2a_types.SecurityScheme(
            mtls_security_scheme=a2a_types.MutualTlsSecurityScheme()
        )
        card = a2a_types.AgentCard(
            name="M",
            security_schemes={"mtls": scheme},
            security_requirements=[
                a2a_types.SecurityRequirement(schemes={"mtls": a2a_types.StringList()})
            ],
        )
        recommendation = recommend_auth_from_card(card)
        assert recommendation is not None
        assert recommendation.auth_type == AuthType.MTLS
