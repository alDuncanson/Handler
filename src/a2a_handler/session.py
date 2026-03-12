"""Session state management for the Handler CLI.

Persists context_id, task_id, and authentication credentials
across CLI invocations for conversation continuity.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from a2a_handler.auth import AuthCredentials
from a2a_handler.common import get_logger

keyring: Any | None

try:
    import keyring as _keyring
    from keyring.errors import KeyringError

    keyring = _keyring
except ImportError:  # pragma: no cover - exercised when keyring dependency is absent
    keyring = None

    class KeyringError(Exception):
        """Fallback KeyringError when keyring is unavailable."""

        pass


logger = get_logger(__name__)

DEFAULT_SESSION_DIRECTORY = Path.home() / ".handler"
SESSION_FILENAME = "sessions.json"
SESSION_DIRECTORY_MODE = 0o700
SESSION_FILE_MODE = 0o600

KEYRING_SERVICE_NAME = "a2a-handler"
CREDENTIAL_STORAGE_KEYRING = "keyring"
CREDENTIAL_STORAGE_PLAINTEXT = "plaintext"


@dataclass
class AgentSession:
    """Session state for a single agent."""

    agent_url: str
    context_id: str | None = None
    task_id: str | None = None
    credentials: AuthCredentials | None = None

    def update(
        self,
        context_id: str | None = None,
        task_id: str | None = None,
        credentials: AuthCredentials | None = None,
    ) -> None:
        """Update session with new values (only if provided)."""
        if context_id is not None:
            self.context_id = context_id
        if task_id is not None:
            self.task_id = task_id
        if credentials is not None:
            self.credentials = credentials

    def clear_credentials(self) -> None:
        """Clear stored credentials."""
        self.credentials = None


@dataclass
class SessionStore:
    """Persistent store for agent sessions."""

    sessions: dict[str, AgentSession] = field(default_factory=dict)
    session_directory: Path = field(default_factory=lambda: DEFAULT_SESSION_DIRECTORY)

    @property
    def session_file_path(self) -> Path:
        """Path to the session file."""
        return self.session_directory / SESSION_FILENAME

    def _harden_path_permissions(self, path: Path, mode: int) -> None:
        """Apply restrictive permissions to session storage paths."""
        try:
            path.chmod(mode)
        except OSError as error:
            logger.warning("Failed to set permissions on %s: %s", path, error)

    def _ensure_directory_exists(self) -> None:
        """Ensure the session directory exists."""
        self.session_directory.mkdir(
            parents=True,
            exist_ok=True,
            mode=SESSION_DIRECTORY_MODE,
        )
        self._harden_path_permissions(self.session_directory, SESSION_DIRECTORY_MODE)

    def _store_credential_in_keyring(self, agent_url: str, value: str) -> bool:
        """Persist credential values in the OS keyring when available."""
        if keyring is None:
            return False

        try:
            keyring.set_password(KEYRING_SERVICE_NAME, agent_url, value)
            return True
        except KeyringError as error:
            logger.warning(
                "Keyring storage unavailable for %s, falling back to plaintext: %s",
                agent_url,
                error,
            )
        except Exception as error:  # pragma: no cover - defensive fallback
            logger.warning(
                "Unexpected keyring failure for %s, falling back to plaintext: %s",
                agent_url,
                error,
            )

        return False

    def _get_credential_from_keyring(self, agent_url: str) -> str | None:
        """Load credential values from the OS keyring."""
        if keyring is None:
            return None

        try:
            return keyring.get_password(KEYRING_SERVICE_NAME, agent_url)
        except KeyringError as error:
            logger.warning(
                "Failed to read keyring credential for %s: %s", agent_url, error
            )
        except Exception as error:  # pragma: no cover - defensive fallback
            logger.warning(
                "Unexpected keyring read failure for %s: %s",
                agent_url,
                error,
            )

        return None

    def _delete_credential_from_keyring(self, agent_url: str) -> None:
        """Remove a credential value from the OS keyring."""
        if keyring is None:
            return

        try:
            keyring.delete_password(KEYRING_SERVICE_NAME, agent_url)
        except KeyringError:
            # Missing/unsupported entries are safe to ignore.
            return
        except Exception as error:  # pragma: no cover - defensive fallback
            logger.warning(
                "Unexpected keyring delete failure for %s: %s",
                agent_url,
                error,
            )

    def _serialize_credentials(
        self,
        agent_url: str,
        credentials: AuthCredentials,
    ) -> dict[str, str | None]:
        """Serialize credentials while storing secret values in keyring."""
        serialized: dict[str, str | None] = {
            "auth_type": credentials.auth_type.value,
            "header_name": credentials.header_name,
        }

        if self._store_credential_in_keyring(agent_url, credentials.value):
            serialized["storage"] = CREDENTIAL_STORAGE_KEYRING
        else:
            serialized["storage"] = CREDENTIAL_STORAGE_PLAINTEXT
            serialized["value"] = credentials.value

        return serialized

    def _deserialize_credentials(
        self,
        agent_url: str,
        cred_data: dict[str, Any],
    ) -> AuthCredentials | None:
        """Deserialize credentials from session data with keyring support."""
        storage = cred_data.get("storage")
        value: str | None = None

        if storage == CREDENTIAL_STORAGE_KEYRING:
            value = self._get_credential_from_keyring(agent_url)
            if value is None and isinstance(cred_data.get("value"), str):
                # Compatibility fallback for mixed-format data.
                value = cred_data["value"]
        elif storage is None:
            # Legacy data may not include storage metadata. Prefer keyring when
            # available so stale plaintext values don't override managed secrets.
            value = self._get_credential_from_keyring(agent_url)
            if value is None and isinstance(cred_data.get("value"), str):
                value = cred_data["value"]
        elif isinstance(cred_data.get("value"), str):
            value = cred_data["value"]

        if value is None:
            logger.warning(
                "Credentials missing for %s (storage=%s)", agent_url, storage
            )
            return None

        normalized_data = {
            "auth_type": cred_data.get("auth_type"),
            "value": value,
            "header_name": cred_data.get("header_name"),
        }

        try:
            return AuthCredentials.from_dict(normalized_data)
        except (KeyError, TypeError, ValueError) as error:
            logger.warning("Invalid credential data for %s: %s", agent_url, error)
            return None

    def load(self) -> None:
        """Load sessions from disk."""
        if self.session_directory.exists():
            self._harden_path_permissions(
                self.session_directory, SESSION_DIRECTORY_MODE
            )
        if not self.session_file_path.exists():
            logger.debug("No session file found at %s", self.session_file_path)
            return

        try:
            self._harden_path_permissions(self.session_file_path, SESSION_FILE_MODE)
            with open(self.session_file_path) as session_file:
                session_data = json.load(session_file)

            for agent_url, agent_session_data in session_data.items():
                if not isinstance(agent_session_data, dict):
                    logger.warning("Skipping invalid session entry for %s", agent_url)
                    continue

                credentials = None
                if cred_data := agent_session_data.get("credentials"):
                    if isinstance(cred_data, dict):
                        credentials = self._deserialize_credentials(
                            agent_url, cred_data
                        )
                    else:
                        logger.warning("Skipping invalid credentials for %s", agent_url)

                self.sessions[agent_url] = AgentSession(
                    agent_url=agent_url,
                    context_id=agent_session_data.get("context_id"),
                    task_id=agent_session_data.get("task_id"),
                    credentials=credentials,
                )

            logger.debug(
                "Loaded %d sessions from %s",
                len(self.sessions),
                self.session_file_path,
            )

        except json.JSONDecodeError as error:
            logger.warning("Failed to parse session file: %s", error)
        except OSError as error:
            logger.warning("Failed to read session file: %s", error)

    def save(self) -> None:
        """Save sessions to disk."""
        self._ensure_directory_exists()

        session_data: dict[str, Any] = {}
        for agent_url, agent_session in self.sessions.items():
            data: dict[str, Any] = {
                "context_id": agent_session.context_id,
                "task_id": agent_session.task_id,
            }
            if agent_session.credentials:
                data["credentials"] = self._serialize_credentials(
                    agent_url,
                    agent_session.credentials,
                )
            session_data[agent_url] = data

        try:
            file_descriptor = os.open(
                self.session_file_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                SESSION_FILE_MODE,
            )
            with os.fdopen(file_descriptor, "w") as session_file:
                json.dump(session_data, session_file, indent=2)
            self._harden_path_permissions(self.session_file_path, SESSION_FILE_MODE)
            logger.debug(
                "Saved %d sessions to %s",
                len(self.sessions),
                self.session_file_path,
            )
        except OSError as error:
            logger.warning("Failed to write session file: %s", error)

    def get(self, agent_url: str) -> AgentSession:
        """Get or create a session for an agent URL."""
        if agent_url not in self.sessions:
            self.sessions[agent_url] = AgentSession(agent_url=agent_url)
            logger.debug("Created new session for %s", agent_url)
        return self.sessions[agent_url]

    def update(
        self,
        agent_url: str,
        context_id: str | None = None,
        task_id: str | None = None,
        credentials: AuthCredentials | None = None,
    ) -> AgentSession:
        """Update session for an agent and save."""
        agent_session = self.get(agent_url)
        agent_session.update(context_id, task_id, credentials)
        self.save()
        logger.debug(
            "Updated session for %s: context_id=%s, task_id=%s, has_credentials=%s",
            agent_url,
            context_id,
            task_id,
            credentials is not None,
        )
        return agent_session

    def set_credentials(
        self,
        agent_url: str,
        credentials: AuthCredentials,
    ) -> AgentSession:
        """Set credentials for an agent."""
        agent_session = self.get(agent_url)
        agent_session.credentials = credentials
        self.save()
        logger.info("Set credentials for %s", agent_url)
        return agent_session

    def clear_credentials(self, agent_url: str) -> None:
        """Clear credentials for an agent."""
        self._delete_credential_from_keyring(agent_url)
        if agent_url in self.sessions:
            self.sessions[agent_url].clear_credentials()
            self.save()
            logger.info("Cleared credentials for %s", agent_url)

    def get_credentials(self, agent_url: str) -> AuthCredentials | None:
        """Get credentials for an agent."""
        if agent_url in self.sessions:
            return self.sessions[agent_url].credentials
        return None

    def clear(self, agent_url: str | None = None) -> None:
        """Clear session(s).

        Args:
            agent_url: If provided, clear only that agent's session.
                      Otherwise, clear all sessions.
        """
        if agent_url:
            if agent_url in self.sessions:
                agent_session = self.sessions[agent_url]
                agent_session.context_id = None
                agent_session.task_id = None
                if agent_session.credentials is None:
                    del self.sessions[agent_url]
                logger.info("Cleared session for %s", agent_url)
        else:
            session_count = len(self.sessions)
            for existing_agent_url in list(self.sessions):
                existing_session = self.sessions[existing_agent_url]
                existing_session.context_id = None
                existing_session.task_id = None
                if existing_session.credentials is None:
                    del self.sessions[existing_agent_url]
            logger.info("Cleared all %d sessions", session_count)
        self.save()

    def list_all(self) -> list[AgentSession]:
        """List all sessions."""
        return list(self.sessions.values())


_global_session_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    """Get the global session store (singleton)."""
    global _global_session_store
    if _global_session_store is None:
        _global_session_store = SessionStore()
        _global_session_store.load()
        logger.debug("Initialized global session store")
    return _global_session_store


def get_session(agent_url: str) -> AgentSession:
    """Get session for an agent URL."""
    return get_session_store().get(agent_url)


def update_session(
    agent_url: str,
    context_id: str | None = None,
    task_id: str | None = None,
) -> AgentSession:
    """Update and persist session for an agent."""
    return get_session_store().update(agent_url, context_id, task_id)


def clear_session(agent_url: str | None = None) -> None:
    """Clear session(s)."""
    get_session_store().clear(agent_url)


def set_credentials(agent_url: str, credentials: AuthCredentials) -> AgentSession:
    """Set credentials for an agent."""
    return get_session_store().set_credentials(agent_url, credentials)


def clear_credentials(agent_url: str) -> None:
    """Clear credentials for an agent."""
    get_session_store().clear_credentials(agent_url)


def get_credentials(agent_url: str) -> AuthCredentials | None:
    """Get credentials for an agent."""
    return get_session_store().get_credentials(agent_url)
