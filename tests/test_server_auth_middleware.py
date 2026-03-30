"""Tests for API key authentication middleware behavior."""

import pytest
from a2a.types import PushNotificationConfig
from a2a.utils.errors import ServerError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from a2a_handler.server.app import (
    APIKeyAuthMiddleware,
    ValidatingPushNotificationConfigStore,
)


def _create_client(api_key: str = "secret-key") -> TestClient:
    async def protected_endpoint(_request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/rpc", protected_endpoint, methods=["POST"])],
        middleware=[
            Middleware(APIKeyAuthMiddleware, api_key=api_key)  # type: ignore[arg-type]
        ],
    )
    return TestClient(app)


def _create_client_with_open_routes(api_key: str = "secret-key") -> TestClient:
    async def handler(_request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/rpc", handler, methods=["POST"]),
            Route("/", handler, methods=["GET"]),
            Route("/.well-known/agent.json", handler, methods=["GET"]),
            Route("/.well-known/agent-card.json", handler, methods=["GET"]),
        ],
        middleware=[
            Middleware(APIKeyAuthMiddleware, api_key=api_key)  # type: ignore[arg-type]
        ],
    )
    return TestClient(app)


def test_rejects_request_without_auth_header() -> None:
    """Protected endpoint rejects requests with no credentials."""
    with _create_client() as client:
        response = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "x"})

    assert response.status_code == 401


def test_accepts_request_with_bearer_token() -> None:
    """Protected endpoint accepts bearer token matching configured API key."""
    with _create_client() as client:
        response = client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "x"},
            headers={"Authorization": "Bearer secret-key"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_accepts_request_with_api_key_header() -> None:
    """Protected endpoint accepts X-API-Key header matching configured API key."""
    with _create_client() as client:
        response = client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "x"},
            headers={"X-API-Key": "secret-key"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_push_config_store_rejects_invalid_webhook_url() -> None:
    """Push config store returns invalid params for malformed callback URLs."""
    store = ValidatingPushNotificationConfigStore()

    with pytest.raises(ServerError) as error:
        await store.set_info(
            "task-123",
            PushNotificationConfig(url="not-a-url"),
        )

    assert "invalid_webhook_url" in str(error.value)


@pytest.mark.asyncio
async def test_push_config_store_accepts_valid_webhook_url() -> None:
    """Push config store keeps valid callback URLs unchanged."""
    store = ValidatingPushNotificationConfigStore()

    await store.set_info(
        "task-123",
        PushNotificationConfig(url="https://example.com/webhook", token="token-123"),
    )

    configs = await store.get_info("task-123")
    assert len(configs) == 1
    assert configs[0].url == "https://example.com/webhook"


def test_get_root_path_bypasses_auth() -> None:
    """GET / bypasses auth and returns 200."""
    with _create_client_with_open_routes() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_accepts_apikey_prefix_in_authorization_header() -> None:
    """Protected endpoint accepts ApiKey prefix in Authorization header."""
    with _create_client() as client:
        response = client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "x"},
            headers={"Authorization": "ApiKey secret-key"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_rejects_wrong_apikey_prefix_value() -> None:
    """Protected endpoint rejects wrong ApiKey value."""
    with _create_client() as client:
        response = client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "x"},
            headers={"Authorization": "ApiKey wrong-key"},
        )

    assert response.status_code == 401


def test_open_paths_bypass_auth() -> None:
    """Paths in OPEN_PATHS bypass authentication."""
    with _create_client_with_open_routes() as client:
        for path in ["/.well-known/agent.json", "/.well-known/agent-card.json"]:
            response = client.get(path)
            assert response.status_code == 200, f"{path} should bypass auth"
            assert response.json() == {"ok": True}
