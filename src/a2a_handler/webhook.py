"""Webhook server for receiving A2A push notifications.

Provides an HTTP server for receiving and displaying push notifications from A2A agents.
"""

import json
import secrets
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a_handler.common import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_STORED_NOTIFICATIONS = 100
NOTIFICATION_TOKEN_HEADER = "x-a2a-notification-token"


@dataclass
class PushNotification:
    """A received push notification."""

    timestamp: datetime
    task_id: str | None
    payload: dict[str, Any]
    headers: dict[str, str]
    state: str | None = None


def _state_label(state: object) -> str | None:
    """Compact label for a task state, whichever serialization it arrived in."""
    if not isinstance(state, str) or not state:
        return None
    # v1.0 serializes task state as the protobuf enum name
    # (e.g. "TASK_STATE_COMPLETED"); show a compact label.
    return state.removeprefix("TASK_STATE_").lower()


def _first_key(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def summarize_push_payload(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(task_id, state)`` from a push notification body.

    A v1.0 agent posts a ``StreamResponse``: one of ``task``, ``statusUpdate``,
    ``artifactUpdate`` or ``message`` wrapping the event. A v0.3 agent posts the
    task itself, with ``id`` and ``status`` at the top level. Both are read.
    """
    task = _first_key(payload, "task")
    if isinstance(task, dict):
        status = _first_key(task, "status") or {}
        state = _first_key(status, "state") if isinstance(status, dict) else None
        return _first_key(task, "id", "taskId", "task_id"), _state_label(state)

    status_update = _first_key(payload, "statusUpdate", "status_update")
    if isinstance(status_update, dict):
        status = _first_key(status_update, "status") or {}
        state = _first_key(status, "state") if isinstance(status, dict) else None
        return _first_key(status_update, "taskId", "task_id"), _state_label(state)

    for key in ("artifactUpdate", "artifact_update", "message"):
        event = _first_key(payload, key)
        if isinstance(event, dict):
            return _first_key(event, "taskId", "task_id"), None

    status = _first_key(payload, "status") or {}
    state = _first_key(status, "state") if isinstance(status, dict) else None
    return _first_key(payload, "id", "taskId", "task_id"), _state_label(state)


@dataclass
class PushNotificationStore:
    """In-memory store for received notifications."""

    notifications: deque[PushNotification] = field(
        default_factory=lambda: deque(maxlen=DEFAULT_MAX_STORED_NOTIFICATIONS)
    )

    def add_notification(self, notification: PushNotification) -> None:
        """Add a notification to the store."""
        self.notifications.append(notification)
        logger.debug(
            "Stored notification for task: %s (total: %d)",
            notification.task_id,
            len(self.notifications),
        )

    def get_all_notifications(self) -> list[PushNotification]:
        """Get all stored notifications."""
        return list(self.notifications)

    def clear_all_notifications(self) -> None:
        """Clear all stored notifications."""
        notification_count = len(self.notifications)
        self.notifications.clear()
        logger.info("Cleared %d stored notifications", notification_count)


notification_store = PushNotificationStore()


async def handle_push_notification(request: Request) -> JSONResponse:
    """Handle incoming push notifications from A2A agents."""
    expected_token = getattr(request.app.state, "expected_token", None)
    request_headers = dict(request.headers)
    presented_token = request_headers.get(NOTIFICATION_TOKEN_HEADER, "")
    if expected_token is not None and not secrets.compare_digest(
        presented_token, expected_token
    ):
        logger.warning("Rejected push notification: missing or wrong token")
        return JSONResponse({"error": "Invalid notification token"}, status_code=401)

    try:
        request_payload = await request.json()
        if not isinstance(request_payload, dict):
            logger.warning("Received non-object JSON in push notification")
            return JSONResponse(
                {"error": "Payload must be a JSON object"}, status_code=400
            )
    except json.JSONDecodeError:
        logger.warning("Received invalid JSON in push notification")
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    task_id, state = summarize_push_payload(request_payload)

    notification = PushNotification(
        timestamp=datetime.now(),
        task_id=task_id,
        payload=request_payload,
        headers=request_headers,
        state=state,
    )
    notification_store.add_notification(notification)

    logger.info("Received push notification for task: %s", task_id)

    print("\nPush Notification Received")
    print(f"Timestamp: {notification.timestamp.isoformat()}")
    if task_id:
        print(f"Task ID: {task_id}")
    if state:
        print(f"State: {state}")
    if presented_token:
        print("Token: present" + (" (verified)" if expected_token is not None else ""))

    print()
    print(json.dumps(request_payload, indent=2, default=str))
    print()

    return JSONResponse({"status": "ok", "received": True})


async def handle_webhook_validation(request: Request) -> JSONResponse:
    """Handle GET requests for webhook validation."""
    logger.info("Webhook validation request received")
    return JSONResponse({"status": "ok", "message": "Webhook is active"})


async def handle_list_notifications(request: Request) -> JSONResponse:
    """List all received notifications."""
    all_notifications = notification_store.get_all_notifications()
    logger.debug("Returning %d stored notifications", len(all_notifications))
    return JSONResponse(
        {
            "count": len(all_notifications),
            "notifications": [
                {
                    "timestamp": notification.timestamp.isoformat(),
                    "task_id": notification.task_id,
                    "state": notification.state,
                    "payload": notification.payload,
                }
                for notification in all_notifications
            ],
        }
    )


async def handle_clear_notifications(request: Request) -> JSONResponse:
    """Clear all stored notifications."""
    notification_store.clear_all_notifications()
    return JSONResponse({"status": "ok", "message": "Notifications cleared"})


def create_webhook_application(expected_token: str | None = None) -> Starlette:
    """Create the webhook Starlette application.

    Args:
        expected_token: When set, a notification is accepted only if its
            ``X-A2A-Notification-Token`` header matches. Pair it with the
            token given to the agent in the push config.
    """
    application_routes = [
        Route("/webhook", handle_push_notification, methods=["POST"]),
        Route("/webhook", handle_webhook_validation, methods=["GET"]),
        Route("/notifications", handle_list_notifications, methods=["GET"]),
        Route("/notifications/clear", handle_clear_notifications, methods=["POST"]),
    ]
    application = Starlette(routes=application_routes)
    application.state.expected_token = expected_token
    return application


def run_webhook_server(
    host: str = "127.0.0.1",
    port: int = 9000,
    token: str | None = None,
) -> None:
    """Start the webhook server.

    Args:
        host: Host address to bind to
        port: Port number to bind to
        token: Require this notification token on every delivery
    """
    print(f"\nStarting webhook server on {host}:{port}")
    if token is not None:
        print("Deliveries must carry the configured notification token")
    print()
    print("Endpoints:")
    print(f"  POST http://{host}:{port}/webhook - Receive notifications")
    print(f"  GET  http://{host}:{port}/webhook - Validation check")
    print(f"  GET  http://{host}:{port}/notifications - List received")
    print(f"  POST http://{host}:{port}/notifications/clear - Clear stored")
    print()
    print(f"Use this URL for push notifications: http://{host}:{port}/webhook")
    print()

    logger.info("Starting webhook server on %s:%d", host, port)
    webhook_application = create_webhook_application(expected_token=token)
    uvicorn.run(webhook_application, host=host, port=port, log_level="warning")
