"""Tests for the TUI application."""

import pytest

from a2a_handler.auth import AuthType
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
