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

    def _set_none_selected(self) -> None:
        """Set no-auth selection and hide auth-specific fields."""
        none_button = self.query_one("#auth-none", RadioButton)
        api_key_button = self.query_one("#auth-api-key", RadioButton)
        bearer_button = self.query_one("#auth-bearer", RadioButton)

        with self.prevent(RadioButton.Changed, RadioSet.Changed):
            none_button.value = True
            api_key_button.value = False
            bearer_button.value = False

        self.query_one("#api-key-fields", Vertical).add_class("hidden")
        self.query_one("#bearer-fields", Vertical).add_class("hidden")

    def _set_api_key_selected(self) -> None:
        """Set API key selection and show API key fields."""
        none_button = self.query_one("#auth-none", RadioButton)
        api_key_button = self.query_one("#auth-api-key", RadioButton)
        bearer_button = self.query_one("#auth-bearer", RadioButton)

        with self.prevent(RadioButton.Changed, RadioSet.Changed):
            none_button.value = False
            api_key_button.value = True
            bearer_button.value = False

        self.query_one("#api-key-fields", Vertical).remove_class("hidden")
        self.query_one("#bearer-fields", Vertical).add_class("hidden")

    def _set_bearer_selected(self) -> None:
        """Set bearer selection and show bearer fields."""
        none_button = self.query_one("#auth-none", RadioButton)
        api_key_button = self.query_one("#auth-api-key", RadioButton)
        bearer_button = self.query_one("#auth-bearer", RadioButton)

        with self.prevent(RadioButton.Changed, RadioSet.Changed):
            none_button.value = False
            api_key_button.value = False
            bearer_button.value = True

        self.query_one("#api-key-fields", Vertical).add_class("hidden")
        self.query_one("#bearer-fields", Vertical).remove_class("hidden")

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
        if event.pressed.id == "auth-api-key":
            self._set_api_key_selected()
            logger.debug("Auth type changed to API Key")
        elif event.pressed.id == "auth-bearer":
            self._set_bearer_selected()
            logger.debug("Auth type changed to Bearer Token")
        else:
            self._set_none_selected()
            logger.debug("Auth type changed to None")

    def get_credentials(self) -> AuthCredentials | None:
        """Get the configured authentication credentials.

        Returns:
            AuthCredentials if auth is configured, None otherwise.
        """
        if self.query_one("#auth-api-key", RadioButton).value:
            api_key = self.query_one("#api-key-input", Input).value
            header_name = (
                self.query_one("#api-key-header-input", Input).value or "X-API-Key"
            )
            if api_key:
                return create_api_key_auth(api_key, header_name=header_name)

        if self.query_one("#auth-bearer", RadioButton).value:
            token = self.query_one("#bearer-token-input", Input).value
            if token:
                return create_bearer_auth(token)

        return None

    def get_auth_type(self) -> AuthType | None:
        """Get the currently selected auth type."""
        if self.query_one("#auth-api-key", RadioButton).value:
            return AuthType.API_KEY
        if self.query_one("#auth-bearer", RadioButton).value:
            return AuthType.BEARER
        return None

    def set_bearer_token(self, token: str) -> None:
        """Preconfigure bearer token authentication."""
        self._set_bearer_selected()
        self.query_one("#bearer-token-input", Input).value = token
        logger.debug("Preconfigured bearer token authentication")

    def set_api_key(self, api_key: str, header_name: str = "X-API-Key") -> None:
        """Preconfigure API key authentication."""
        self._set_api_key_selected()
        self.query_one("#api-key-input", Input).value = api_key
        self.query_one("#api-key-header-input", Input).value = header_name
        logger.debug("Preconfigured api key authentication")

    def clear(self) -> None:
        """Reset auth fields to no authentication selected."""
        self.query_one("#api-key-input", Input).value = ""
        self.query_one("#api-key-header-input", Input).value = ""
        self.query_one("#bearer-token-input", Input).value = ""
        self._set_none_selected()
