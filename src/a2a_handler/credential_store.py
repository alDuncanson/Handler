"""Persistent auth credential storage separate from conversation sessions."""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_dir

from a2a_handler.auth import AuthCredentials
from a2a_handler.common import get_logger

logger = get_logger(__name__)

DEFAULT_CREDENTIAL_DIRECTORY = Path(user_data_dir("handler"))
CREDENTIAL_FILENAME = "credentials.json"
_OWNER_RW = stat.S_IRUSR | stat.S_IWUSR  # 0o600


def _set_owner_only_permissions(path: Path) -> None:
    """Restrict file permissions to owner read/write (0o600)."""
    try:
        path.chmod(_OWNER_RW)
    except OSError:
        pass


@dataclass
class CredentialStore:
    """Persistent store for per-agent authentication credentials."""

    credentials_by_url: dict[str, AuthCredentials] = field(default_factory=dict)
    credential_directory: Path = field(
        default_factory=lambda: DEFAULT_CREDENTIAL_DIRECTORY
    )

    @property
    def credential_file_path(self) -> Path:
        """Path to the credential file."""
        return self.credential_directory / CREDENTIAL_FILENAME

    def _ensure_directory_exists(self) -> None:
        """Ensure the credential directory exists."""
        self.credential_directory.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        """Load credentials from disk."""
        if not self.credential_file_path.exists():
            logger.debug("No credential file found at %s", self.credential_file_path)
            return

        try:
            with open(self.credential_file_path) as credential_file:
                credential_data = json.load(credential_file)

            if not isinstance(credential_data, dict):
                logger.warning(
                    "Ignoring credential file %s: root must be an object",
                    self.credential_file_path,
                )
                return

            self.credentials_by_url = {}
            for agent_url, serialized in credential_data.items():
                if not isinstance(agent_url, str) or not isinstance(serialized, dict):
                    continue
                self.credentials_by_url[agent_url] = AuthCredentials.from_dict(
                    serialized
                )

            logger.debug(
                "Loaded %d credential entries from %s",
                len(self.credentials_by_url),
                self.credential_file_path,
            )
        except json.JSONDecodeError as error:
            logger.warning(
                "Failed to parse credential file %s: %s",
                self.credential_file_path,
                error,
            )
        except OSError as error:
            logger.warning(
                "Failed to read credential file %s: %s",
                self.credential_file_path,
                error,
            )

    def save(self) -> None:
        """Save credentials to disk atomically."""
        self._ensure_directory_exists()

        serialized = {
            agent_url: credentials.to_dict()
            for agent_url, credentials in self.credentials_by_url.items()
        }

        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=self.credential_directory,
                prefix=".credentials-",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w") as tmp_file:
                    json.dump(serialized, tmp_file, indent=2)
                os.replace(tmp_path, self.credential_file_path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise

            _set_owner_only_permissions(self.credential_file_path)
            logger.debug(
                "Saved %d credential entries to %s",
                len(self.credentials_by_url),
                self.credential_file_path,
            )
        except OSError as error:
            logger.warning("Failed to write credential file: %s", error)

    def set(self, agent_url: str, credentials: AuthCredentials) -> None:
        """Set credentials for an agent and persist them."""
        self.credentials_by_url[agent_url] = credentials
        self.save()
        logger.info("Set credentials for %s", agent_url)

    def get(self, agent_url: str) -> AuthCredentials | None:
        """Get credentials for an agent."""
        return self.credentials_by_url.get(agent_url)

    def clear(self, agent_url: str) -> None:
        """Clear credentials for an agent if they exist."""
        if agent_url in self.credentials_by_url:
            del self.credentials_by_url[agent_url]
            self.save()
            logger.info("Cleared credentials for %s", agent_url)

    def list_all(self) -> dict[str, AuthCredentials]:
        """Return a copy of all stored credentials."""
        return dict(self.credentials_by_url)


_global_credential_store: CredentialStore | None = None


def get_credential_store() -> CredentialStore:
    """Get the global credential store singleton."""
    global _global_credential_store
    if _global_credential_store is None:
        _global_credential_store = CredentialStore()
        _global_credential_store.load()
        logger.debug("Initialized global credential store")
    return _global_credential_store


def set_credentials(agent_url: str, credentials: AuthCredentials) -> None:
    """Persist credentials for an agent."""
    get_credential_store().set(agent_url, credentials)


def clear_credentials(agent_url: str) -> None:
    """Remove persisted credentials for an agent."""
    get_credential_store().clear(agent_url)


def get_credentials(agent_url: str) -> AuthCredentials | None:
    """Get persisted credentials for an agent."""
    return get_credential_store().get(agent_url)
