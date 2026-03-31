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
    create_oauth2_auth,
    parse_header_string,
)
from a2a_handler.common import get_logger

logger = get_logger(__name__)


class AuthPanel(Vertical):
    """Panel for configuring authentication credentials."""

    can_focus = False

    def _select_auth_button(self, button_id: str) -> None:
        """Synchronously select a single auth radio button."""
        radio_set = self.query_one("#auth-type-selector", RadioSet)
        buttons = list(radio_set.query(RadioButton))
        button = self.query_one(f"#{button_id}", RadioButton)
        with radio_set.prevent(RadioButton.Changed, RadioSet.Changed):
            for candidate in buttons:
                candidate.value = candidate is button
        radio_set._pressed_button = button
        radio_set._selected = buttons.index(button)
        self._apply_auth_specific_field_visibility()

    def _hide_auth_specific_fields(self) -> None:
        """Hide all auth-specific field groups."""
        self.query_one("#api-key-fields", Vertical).add_class("hidden")
        self.query_one("#bearer-fields", Vertical).add_class("hidden")
        self.query_one("#mtls-fields", Vertical).add_class("hidden")
        self.query_one("#oauth2-fields", Vertical).add_class("hidden")

    def _apply_auth_specific_field_visibility(self) -> None:
        """Show only the field group for the selected auth type."""
        self._hide_auth_specific_fields()
        if self.query_one("#auth-api-key", RadioButton).value:
            self.query_one("#api-key-fields", Vertical).remove_class("hidden")
        elif self.query_one("#auth-bearer", RadioButton).value:
            self.query_one("#bearer-fields", Vertical).remove_class("hidden")
        elif self.query_one("#auth-mtls", RadioButton).value:
            self.query_one("#mtls-fields", Vertical).remove_class("hidden")
        elif self.query_one("#auth-oauth2", RadioButton).value:
            self.query_one("#oauth2-fields", Vertical).remove_class("hidden")

    def _set_none_selected(self) -> None:
        """Set no-auth selection and hide auth-specific fields."""
        self._select_auth_button("auth-none")

    def _set_api_key_selected(self) -> None:
        """Set API key selection and show API key fields."""
        self._select_auth_button("auth-api-key")

    def _set_bearer_selected(self) -> None:
        """Set bearer selection and show bearer fields."""
        self._select_auth_button("auth-bearer")

    def _set_mtls_selected(self) -> None:
        """Set mTLS selection and show mTLS fields."""
        self._select_auth_button("auth-mtls")

    def _set_oauth2_selected(self) -> None:
        """Set OAuth2 selection and show OAuth2 fields."""
        self._select_auth_button("auth-oauth2")

    def compose(self) -> ComposeResult:
        yield Label("Authentication Type")
        with RadioSet(id="auth-type-selector"):
            yield RadioButton("None", id="auth-none", value=True)
            yield RadioButton("API Key", id="auth-api-key")
            yield RadioButton("Bearer Token", id="auth-bearer")
            yield RadioButton("mTLS (Client Certificate)", id="auth-mtls")
            yield RadioButton("OAuth2 (Client Credentials)", id="auth-oauth2")

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

        with Vertical(id="oauth2-fields", classes="auth-fields hidden"):
            yield Label("Token URL")
            yield Input(
                placeholder="https://example.com/oauth/token", id="oauth2-token-url-input"
            )
            yield Label("Client ID")
            yield Input(
                placeholder="Enter client ID", id="oauth2-client-id-input"
            )
            yield Label("Client Secret")
            yield Input(
                placeholder="Enter client secret",
                id="oauth2-client-secret-input",
                password=True,
            )
            yield Label("Scopes (optional, space-separated)")
            yield Input(placeholder="read write", id="oauth2-scopes-input")

        yield Label("Custom Headers (optional, semicolon-separated)")
        yield Input(
            placeholder="x-user-id: me@mydomain.com; x-org: acme",
            id="custom-headers-input",
        )

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle auth type selection changes."""
        self._apply_auth_specific_field_visibility()
        if event.pressed.id == "auth-api-key":
            logger.debug("Auth type changed to API Key")
        elif event.pressed.id == "auth-bearer":
            logger.debug("Auth type changed to Bearer Token")
        elif event.pressed.id == "auth-mtls":
            logger.debug("Auth type changed to mTLS")
        elif event.pressed.id == "auth-oauth2":
            logger.debug("Auth type changed to OAuth2")
        else:
            logger.debug("Auth type changed to None")

    def _parse_custom_headers(self) -> dict[str, str] | None:
        """Parse the optional custom-headers field into a header dictionary."""
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
                logger.warning("Skipping invalid custom header: %s", line)

        return headers or None

    def get_credentials(self) -> AuthCredentials | None:
        """Get the configured authentication credentials.

        Returns:
            AuthCredentials if auth is configured, None otherwise.
        """
        credentials: AuthCredentials | None = None

        if self.query_one("#auth-api-key", RadioButton).value:
            api_key = self.query_one("#api-key-input", Input).value
            header_name = (
                self.query_one("#api-key-header-input", Input).value or "X-API-Key"
            )
            if api_key:
                credentials = create_api_key_auth(api_key, header_name=header_name)

        elif self.query_one("#auth-bearer", RadioButton).value:
            token = self.query_one("#bearer-token-input", Input).value
            if token:
                credentials = create_bearer_auth(token)

        elif self.query_one("#auth-mtls", RadioButton).value:
            cert_path = self.query_one("#mtls-cert-input", Input).value.strip()
            key_path = self.query_one("#mtls-key-input", Input).value.strip()
            ca_cert_path = self.query_one("#mtls-ca-input", Input).value.strip() or None
            if cert_path and key_path:
                try:
                    credentials = create_mtls_auth(cert_path, key_path, ca_cert_path)
                except FileNotFoundError:
                    logger.warning("mTLS cert/key path does not exist")

        elif self.query_one("#auth-oauth2", RadioButton).value:
            token_url = self.query_one("#oauth2-token-url-input", Input).value.strip()
            client_id = self.query_one("#oauth2-client-id-input", Input).value.strip()
            client_secret = (
                self.query_one("#oauth2-client-secret-input", Input).value.strip()
            )
            scopes_raw = self.query_one("#oauth2-scopes-input", Input).value.strip()
            scopes = scopes_raw.split() if scopes_raw else None
            if token_url and client_id and client_secret:
                credentials = create_oauth2_auth(
                    token_url, client_id, client_secret, scopes
                )

        custom_headers = self._parse_custom_headers()
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
        if self.query_one("#auth-api-key", RadioButton).value:
            return AuthType.API_KEY
        if self.query_one("#auth-bearer", RadioButton).value:
            return AuthType.BEARER
        if self.query_one("#auth-mtls", RadioButton).value:
            return AuthType.MTLS
        if self.query_one("#auth-oauth2", RadioButton).value:
            return AuthType.OAUTH2
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

    def set_mtls(
        self,
        cert_path: str,
        key_path: str,
        ca_cert_path: str | None = None,
    ) -> None:
        """Preconfigure mTLS authentication."""
        self._set_mtls_selected()
        self.query_one("#mtls-cert-input", Input).value = cert_path
        self.query_one("#mtls-key-input", Input).value = key_path
        self.query_one("#mtls-ca-input", Input).value = ca_cert_path or ""
        logger.debug("Preconfigured mTLS authentication")

    def set_oauth2(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scopes: list[str] | None = None,
    ) -> None:
        """Preconfigure OAuth2 client credentials authentication."""
        self._set_oauth2_selected()
        self.query_one("#oauth2-token-url-input", Input).value = token_url
        self.query_one("#oauth2-client-id-input", Input).value = client_id
        self.query_one("#oauth2-client-secret-input", Input).value = client_secret
        self.query_one("#oauth2-scopes-input", Input).value = (
            " ".join(scopes) if scopes else ""
        )
        logger.debug("Preconfigured OAuth2 authentication")

    def set_custom_headers(self, headers: dict[str, str] | None) -> None:
        """Preconfigure custom headers from a dictionary."""
        headers_input = self.query_one("#custom-headers-input", Input)
        if not headers:
            headers_input.value = ""
            return
        headers_input.value = "; ".join(
            f"{name}: {value}" for name, value in headers.items()
        )

    def clear(self) -> None:
        """Reset auth fields to no authentication selected."""
        self.query_one("#api-key-input", Input).value = ""
        self.query_one("#api-key-header-input", Input).value = ""
        self.query_one("#bearer-token-input", Input).value = ""
        self.query_one("#mtls-cert-input", Input).value = ""
        self.query_one("#mtls-key-input", Input).value = ""
        self.query_one("#mtls-ca-input", Input).value = ""
        self.query_one("#oauth2-token-url-input", Input).value = ""
        self.query_one("#oauth2-client-id-input", Input).value = ""
        self.query_one("#oauth2-client-secret-input", Input).value = ""
        self.query_one("#oauth2-scopes-input", Input).value = ""
        self.query_one("#custom-headers-input", Input).value = ""
        self._set_none_selected()
