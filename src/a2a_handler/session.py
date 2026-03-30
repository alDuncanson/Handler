"""Conversation session state management for Handler.

Persists context_id, task_id, and recency metadata across invocations for
conversation continuity.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

from a2a_handler.common import get_logger

logger = get_logger(__name__)

DEFAULT_SESSION_DIRECTORY = Path(user_data_dir("handler"))
SESSION_FILENAME = "sessions.json"
_OWNER_RW = stat.S_IRUSR | stat.S_IWUSR  # 0o600


def _set_owner_only_permissions(path: Path) -> None:
    """Restrict file permissions to owner read/write (0o600).

    Silently ignored on platforms where chmod is not effective (e.g. Windows).
    """
    try:
        path.chmod(_OWNER_RW)
    except OSError:
        pass


def _current_timestamp() -> str:
    """Return an ISO 8601 UTC timestamp for recency tracking."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentSession:
    """Conversation session state for a single agent URL."""

    agent_url: str
    context_id: str | None = None
    task_id: str | None = None
    last_used_at: str | None = None

    def update(
        self,
        context_id: str | None = None,
        task_id: str | None = None,
        last_used_at: str | None = None,
    ) -> None:
        """Update session with new values (only if provided)."""
        if context_id is not None:
            self.context_id = context_id
        if task_id is not None:
            self.task_id = task_id
        if last_used_at is not None:
            self.last_used_at = last_used_at


@dataclass
class SessionStore:
    """Persistent store for conversation session state."""

    sessions: dict[str, AgentSession] = field(default_factory=dict)
    session_directory: Path = field(default_factory=lambda: DEFAULT_SESSION_DIRECTORY)

    @property
    def session_file_path(self) -> Path:
        """Path to the session file."""
        return self.session_directory / SESSION_FILENAME

    def _ensure_directory_exists(self) -> None:
        """Ensure the session directory exists."""
        self.session_directory.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        """Load sessions from disk."""
        if not self.session_file_path.exists():
            logger.debug("No session file found at %s", self.session_file_path)
            return

        try:
            with open(self.session_file_path) as session_file:
                session_data = json.load(session_file)

            if not isinstance(session_data, dict):
                logger.warning(
                    "Ignoring session file %s: root must be an object",
                    self.session_file_path,
                )
                return

            self.sessions = {}
            for agent_url, agent_session_data in session_data.items():
                if not isinstance(agent_url, str) or not isinstance(
                    agent_session_data, dict
                ):
                    continue
                self.sessions[agent_url] = AgentSession(
                    agent_url=agent_url,
                    context_id=agent_session_data.get("context_id"),
                    task_id=agent_session_data.get("task_id"),
                    last_used_at=agent_session_data.get("last_used_at"),
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
        """Save sessions to disk atomically."""
        self._ensure_directory_exists()

        session_data: dict[str, Any] = {}
        for agent_url, agent_session in self.sessions.items():
            session_data[agent_url] = {
                "context_id": agent_session.context_id,
                "task_id": agent_session.task_id,
                "last_used_at": agent_session.last_used_at,
            }

        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=self.session_directory,
                prefix=".sessions-",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w") as tmp_file:
                    json.dump(session_data, tmp_file, indent=2)
                os.replace(tmp_path, self.session_file_path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise

            _set_owner_only_permissions(self.session_file_path)

            logger.debug(
                "Saved %d sessions to %s",
                len(self.sessions),
                self.session_file_path,
            )
        except OSError as error:
            logger.warning("Failed to write session file: %s", error)

    def find(self, agent_url: str) -> AgentSession | None:
        """Look up a session without creating one."""
        return self.sessions.get(agent_url)

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
    ) -> AgentSession:
        """Update session for an agent and save."""
        agent_session = self.get(agent_url)
        agent_session.update(
            context_id=context_id,
            task_id=task_id,
            last_used_at=_current_timestamp(),
        )
        self.save()
        logger.debug(
            "Updated session for %s: context_id=%s, task_id=%s",
            agent_url,
            context_id,
            task_id,
        )
        return agent_session

    def set_conversation(
        self,
        agent_url: str,
        context_id: str | None,
        task_id: str | None,
    ) -> AgentSession:
        """Replace saved conversation IDs for an agent and save."""
        agent_session = self.get(agent_url)
        agent_session.context_id = context_id
        agent_session.task_id = task_id
        agent_session.last_used_at = _current_timestamp()
        self.save()
        logger.debug(
            "Set conversation for %s: context_id=%s, task_id=%s",
            agent_url,
            context_id,
            task_id,
        )
        return agent_session

    def mark_recent(self, agent_url: str) -> AgentSession:
        """Update recency metadata without changing conversation IDs."""
        agent_session = self.get(agent_url)
        agent_session.last_used_at = _current_timestamp()
        self.save()
        logger.debug("Marked %s as recent", agent_url)
        return agent_session

    def clear(self, agent_url: str | None = None) -> None:
        """Clear session(s)."""
        if agent_url:
            if agent_url in self.sessions:
                del self.sessions[agent_url]
                logger.info("Cleared session for %s", agent_url)
        else:
            session_count = len(self.sessions)
            self.sessions.clear()
            logger.info("Cleared all %d sessions", session_count)
        self.save()

    def list_all(self) -> list[AgentSession]:
        """List all sessions ordered by recency."""
        return sorted(
            self.sessions.values(),
            key=lambda session: (session.last_used_at or "", session.agent_url),
            reverse=True,
        )

    def recent_agent_urls(self, limit: int | None = None) -> list[str]:
        """Return recently used agent URLs in MRU order."""
        urls = [
            session.agent_url for session in self.list_all() if session.last_used_at
        ]
        if limit is not None:
            return urls[:limit]
        return urls


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
