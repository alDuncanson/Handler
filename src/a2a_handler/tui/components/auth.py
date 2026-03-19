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
    create_mtls_auth,
    parse_header_string,
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
            yield RadioButton("mTLS (Client Certificate)", id="auth-mtls")

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

        with Vertical(id="mtls-fields", classes="auth-fields hidden"):
            yield Label("Client Certificate")
            yield Input(placeholder="/path/to/client.crt", id="mtls-cert-input")
            yield Label("Client Private Key")
            yield Input(placeholder="/path/to/client.key", id="mtls-key-input")
            yield Label("CA Certificate (optional)")
            yield Input(placeholder="/path/to/ca.crt", id="mtls-ca-input")

        yield Label("Custom Headers (optional, semicolon-separated)")
        yield Input(
            placeholder="x-user-id: me@mydomain.com; x-org: acme",
            id="custom-headers-input",
        )

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle auth type selection changes."""
        api_key_fields = self.query_one("#api-key-fields", Vertical)
        bearer_fields = self.query_one("#bearer-fields", Vertical)
        mtls_fields = self.query_one("#mtls-fields", Vertical)

        api_key_fields.add_class("hidden")
        bearer_fields.add_class("hidden")
        mtls_fields.add_class("hidden")

        if event.pressed.id == "auth-api-key":
            api_key_fields.remove_class("hidden")
            logger.debug("Auth type changed to API Key")
        elif event.pressed.id == "auth-bearer":
            bearer_fields.remove_class("hidden")
            logger.debug("Auth type changed to Bearer Token")
        elif event.pressed.id == "auth-mtls":
            mtls_fields.remove_class("hidden")
            logger.debug("Auth type changed to mTLS")
        else:
            logger.debug("Auth type changed to None")

    def _parse_custom_headers(self) -> dict[str, str] | None:
        raw = self.query_one("#custom-headers-input", Input).value.strip()
        if not raw:
            return None
        headers: dict[str, str] = {}
        for line in raw.split(";"):
            line = line.strip()
            if not line:
                continue
            try:
                name, value = parse_header_string(line)
                headers[name] = value
            except ValueError:
                logger.warning("Skipping invalid header: %s", line)
        return headers or None

    def get_credentials(self) -> AuthCredentials | None:
        """Get the configured authentication credentials.

        Returns:
            AuthCredentials if auth is configured, None otherwise.
        """
        radio_set = self.query_one("#auth-type-selector", RadioSet)
        pressed = radio_set.pressed_button
        custom_headers = self._parse_custom_headers()

        credentials: AuthCredentials | None = None

        if pressed is not None and pressed.id == "auth-api-key":
            api_key = self.query_one("#api-key-input", Input).value
            header_name = (
                self.query_one("#api-key-header-input", Input).value or "X-API-Key"
            )
            if api_key:
                credentials = create_api_key_auth(api_key, header_name=header_name)

        elif pressed is not None and pressed.id == "auth-bearer":
            token = self.query_one("#bearer-token-input", Input).value
            if token:
                credentials = create_bearer_auth(token)

        elif pressed is not None and pressed.id == "auth-mtls":
            cert_path = self.query_one("#mtls-cert-input", Input).value
            key_path = self.query_one("#mtls-key-input", Input).value
            ca_cert_path = self.query_one("#mtls-ca-input", Input).value or None
            if cert_path and key_path:
                try:
                    credentials = create_mtls_auth(cert_path, key_path, ca_cert_path)
                except FileNotFoundError:
                    logger.warning("mTLS certificate file not found")

        if custom_headers:
            if credentials is None:
                credentials = AuthCredentials(
                    auth_type=AuthType.BEARER,
                    custom_headers=custom_headers,
                )
            else:
                credentials.custom_headers = custom_headers

        return credentials

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
        elif pressed.id == "auth-mtls":
            return AuthType.MTLS
        return None

    def set_bearer_token(self, token: str) -> None:
        """Preconfigure bearer token authentication."""
        self.query_one("#bearer-token-input", Input).value = token
        self.query_one("#auth-bearer", RadioButton).value = True

        # Ensure fields are visible even if no RadioSet event is emitted.
        self.query_one("#api-key-fields", Vertical).add_class("hidden")
        self.query_one("#bearer-fields", Vertical).remove_class("hidden")
        logger.debug("Preconfigured bearer token authentication")
