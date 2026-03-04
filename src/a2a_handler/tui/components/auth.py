"""Authentication panel component for configuring agent auth."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, RadioButton, RadioSet

from a2a_handler.auth import (
    AuthCredentials,
    AuthType,
    create_api_key_auth,
    create_bearer_auth,
)
from a2a_handler.common import get_logger

logger = get_logger(__name__)


class AuthPanel(Vertical):
    """Panel for configuring authentication credentials."""

    can_focus = False

    def compose(self) -> ComposeResult:
        yield Label("Authentication Type")
        with RadioSet(id="auth-type-selector"):
            yield RadioButton("None", id="auth-none", value=True)
            yield RadioButton("API Key", id="auth-api-key")
            yield RadioButton("Bearer Token", id="auth-bearer")

        with Vertical(id="api-key-fields", classes="auth-fields hidden"):
            yield Label("API Key")
            yield Input(placeholder="Enter API key", id="api-key-input", password=True)
            yield Label("Header Name")
            yield Input(placeholder="X-API-Key", id="api-key-header-input")

        with Vertical(id="bearer-fields", classes="auth-fields hidden"):
            yield Label("Bearer Token")
            yield Input(
                placeholder="Enter bearer token", id="bearer-token-input", password=True
            )

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle auth type selection changes."""
        api_key_fields = self.query_one("#api-key-fields", Vertical)
        bearer_fields = self.query_one("#bearer-fields", Vertical)

        api_key_fields.add_class("hidden")
        bearer_fields.add_class("hidden")

        if event.pressed.id == "auth-api-key":
            api_key_fields.remove_class("hidden")
            logger.debug("Auth type changed to API Key")
        elif event.pressed.id == "auth-bearer":
            bearer_fields.remove_class("hidden")
            logger.debug("Auth type changed to Bearer Token")
        else:
            logger.debug("Auth type changed to None")

    def get_credentials(self) -> AuthCredentials | None:
        """Get the configured authentication credentials.

        Returns:
            AuthCredentials if auth is configured, None otherwise.
        """
        radio_set = self.query_one("#auth-type-selector", RadioSet)
        pressed = radio_set.pressed_button

        if pressed is None or pressed.id == "auth-none":
            return None

        if pressed.id == "auth-api-key":
            api_key = self.query_one("#api-key-input", Input).value
            header_name = (
                self.query_one("#api-key-header-input", Input).value or "X-API-Key"
            )
            if api_key:
                return create_api_key_auth(api_key, header_name=header_name)

        elif pressed.id == "auth-bearer":
            token = self.query_one("#bearer-token-input", Input).value
            if token:
                return create_bearer_auth(token)

        return None

    def get_auth_type(self) -> AuthType | None:
        """Get the currently selected auth type."""
        radio_set = self.query_one("#auth-type-selector", RadioSet)
        pressed = radio_set.pressed_button

        if pressed is None or pressed.id == "auth-none":
            return None
        elif pressed.id == "auth-api-key":
            return AuthType.API_KEY
        elif pressed.id == "auth-bearer":
            return AuthType.BEARER
        return None

    def set_bearer_token(self, token: str) -> None:
        """Preconfigure bearer token authentication."""
        self.query_one("#bearer-token-input", Input).value = token
        self.query_one("#auth-bearer", RadioButton).value = True

        # Ensure fields are visible even if no RadioSet event is emitted.
        self.query_one("#api-key-fields", Vertical).add_class("hidden")
        self.query_one("#bearer-fields", Vertical).remove_class("hidden")
        logger.debug("Preconfigured bearer token authentication")
