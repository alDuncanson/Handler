"""Tests for the TUI application."""

from unittest.mock import AsyncMock, patch

import pytest
from a2a.types import AgentCard

from a2a_handler.auth import AuthType, create_bearer_auth
from a2a_handler.tui import HandlerTUI
from a2a_handler.tui.components import TabbedMessagesPanel


@pytest.mark.asyncio
async def test_app_startup():
    """Test that the app starts up and displays the initial state."""
    app = HandlerTUI()
    async with app.run_test() as _:
        assert app.query_one("#root-container")


@pytest.mark.asyncio
async def test_app_startup_with_initial_bearer_token():
    """Test startup preconfigures bearer token auth when provided."""
    app = HandlerTUI(initial_bearer_token="test-token")
    async with app.run_test() as _:
        messages_panel = app.query_one("#messages-container", TabbedMessagesPanel)
        credentials = messages_panel.get_auth_credentials()

        assert credentials is not None
        assert credentials.auth_type == AuthType.BEARER
        assert credentials.value == "test-token"


@pytest.mark.asyncio
async def test_connect_to_agent_uses_credentials_for_card_request():
    """Test connect flow applies auth credentials before fetching card."""
    app = HandlerTUI()
    app.http_client = AsyncMock()
    credentials = create_bearer_auth("test-token")
    mock_card = AsyncMock(spec=AgentCard)

    with patch("a2a_handler.tui.app.A2AService") as mock_service_cls:
        mock_service = AsyncMock()
        mock_service.get_card.return_value = mock_card
        mock_service_cls.return_value = mock_service

        card = await app._connect_to_agent("https://agent.example.com", credentials)

        assert card is mock_card
        mock_service_cls.assert_called_once_with(
            app.http_client,
            "https://agent.example.com",
            credentials=credentials,
        )


@pytest.mark.asyncio
async def test_tui_uses_resolved_credentials_when_auth_panel_empty():
    """TUI resolves configured credentials when auth panel has no value."""
    app = HandlerTUI()
    async with app.run_test() as _:
        resolved_credentials = create_bearer_auth("resolved-token")
        mock_card = AsyncMock(spec=AgentCard)

        with (
            patch("a2a_handler.tui.app.resolve_auth_credentials") as mock_resolve,
            patch("a2a_handler.tui.app.A2AService") as mock_service_cls,
        ):
            mock_resolve.return_value = resolved_credentials
            mock_service = AsyncMock()
            mock_service.get_card.return_value = mock_card
            mock_service_cls.return_value = mock_service

            card = await app._connect_to_agent(
                "https://agent.example.com",
                app._resolve_auth_for_agent("https://agent.example.com"),
            )

            assert card is mock_card
            mock_resolve.assert_called_once_with("https://agent.example.com")
            mock_service_cls.assert_called_once_with(
                app.http_client,
                "https://agent.example.com",
                credentials=resolved_credentials,
            )
