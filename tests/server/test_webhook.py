"""Tests for the webhook server module."""

from datetime import datetime

import pytest
from starlette.testclient import TestClient

from a2a_handler.webhook import (
    PushNotification,
    PushNotificationStore,
    create_webhook_application,
)


class TestPushNotification:
    """Tests for PushNotification dataclass."""

    def test_create_notification(self):
        """Test creating a notification."""
        timestamp = datetime.now()
        notification = PushNotification(
            timestamp=timestamp,
            task_id="task-123",
            payload={"status": {"state": "completed"}},
            headers={"content-type": "application/json"},
        )

        assert notification.timestamp == timestamp
        assert notification.task_id == "task-123"
        assert notification.payload["status"]["state"] == "completed"
        assert notification.headers["content-type"] == "application/json"

    def test_create_notification_without_task_id(self):
        """Test creating a notification without task_id."""
        notification = PushNotification(
            timestamp=datetime.now(),
            task_id=None,
            payload={},
            headers={},
        )

        assert notification.task_id is None


class TestPushNotificationStore:
    """Tests for PushNotificationStore."""

    def test_add_notification(self):
        """Test adding a notification to the store."""
        store = PushNotificationStore()
        notification = PushNotification(
            timestamp=datetime.now(),
            task_id="task-123",
            payload={},
            headers={},
        )

        store.add_notification(notification)
        assert len(store.notifications) == 1

    def test_get_all_notifications(self):
        """Test getting all notifications."""
        store = PushNotificationStore()
        notification1 = PushNotification(
            timestamp=datetime.now(),
            task_id="task-1",
            payload={},
            headers={},
        )
        notification2 = PushNotification(
            timestamp=datetime.now(),
            task_id="task-2",
            payload={},
            headers={},
        )

        store.add_notification(notification1)
        store.add_notification(notification2)

        all_notifications = store.get_all_notifications()
        assert len(all_notifications) == 2

    def test_clear_all_notifications(self):
        """Test clearing all notifications."""
        store = PushNotificationStore()
        notification = PushNotification(
            timestamp=datetime.now(),
            task_id="task-123",
            payload={},
            headers={},
        )

        store.add_notification(notification)
        store.clear_all_notifications()

        assert len(store.notifications) == 0


class TestWebhookApplication:
    """Tests for the webhook Starlette application."""

    @pytest.fixture
    def client(self):
        """Create a test client for the webhook application."""
        application = create_webhook_application()
        return TestClient(application)

    def test_webhook_validation_get(self, client):
        """Test GET request for webhook validation."""
        response = client.get("/webhook")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "message" in data

    def test_webhook_receive_notification(self, client):
        """Test POST request to receive notification."""
        payload = {
            "id": "task-123",
            "status": {"state": "completed"},
        }

        response = client.post("/webhook", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["received"] is True

    def test_webhook_invalid_json(self, client):
        """Test POST request with invalid JSON."""
        response = client.post(
            "/webhook",
            content="not valid json",
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_list_notifications(self, client):
        """Test listing received notifications."""
        response = client.get("/notifications")

        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "notifications" in data

    def test_clear_notifications(self, client):
        """Test clearing notifications."""
        response = client.post("/notifications/clear")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_webhook_non_object_json_rejected(self, client):
        """Test POST with non-object JSON payload returns 400."""
        response = client.post(
            "/webhook",
            json=[1, 2, 3],
        )

        assert response.status_code == 400
        data = response.json()
        assert "JSON object" in data["error"]

    def test_webhook_stores_notification_with_task_id(self, client):
        """Test notification with 'id' field is stored with correct task_id."""
        client.post("/notifications/clear")

        payload = {"id": "task-123", "status": {"state": "working"}}
        client.post("/webhook", json=payload)

        response = client.get("/notifications")
        data = response.json()
        assert data["count"] >= 1
        stored = data["notifications"][-1]
        assert stored["task_id"] == "task-123"

    def test_webhook_stores_notification_without_task_id(self, client):
        """Test notification without id fields is stored with task_id=None."""
        client.post("/notifications/clear")

        payload = {"status": {"state": "working"}}
        client.post("/webhook", json=payload)

        response = client.get("/notifications")
        data = response.json()
        assert data["count"] >= 1
        stored = data["notifications"][-1]
        assert stored["task_id"] is None

    def test_webhook_notification_with_auth_token(self, client):
        """Test notification with x-a2a-notification-token header."""
        client.post("/notifications/clear")

        payload = {"id": "task-456"}
        response = client.post(
            "/webhook",
            json=payload,
            headers={"x-a2a-notification-token": "abcdefghijklmnopqrstuvwxyz"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
