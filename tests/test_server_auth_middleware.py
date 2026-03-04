"""Tests for API key authentication middleware behavior."""

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from a2a_handler.server.app import APIKeyAuthMiddleware


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
