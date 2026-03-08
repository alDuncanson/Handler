"""Tests for the session state management module."""

import json
import stat
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from a2a_handler.auth import create_bearer_auth
from a2a_handler.session import (
    CREDENTIAL_STORAGE_KEYRING,
    CREDENTIAL_STORAGE_PLAINTEXT,
    AgentSession,
    SessionStore,
)


class TestAgentSession:
    """Tests for AgentSession dataclass."""

    def test_create_session_with_url_only(self):
        """Test creating a session with just the URL."""
        session = AgentSession(agent_url="http://localhost:8000")

        assert session.agent_url == "http://localhost:8000"
        assert session.context_id is None
        assert session.task_id is None

    def test_create_session_with_all_fields(self):
        """Test creating a session with all fields."""
        session = AgentSession(
            agent_url="http://localhost:8000",
            context_id="ctx-123",
            task_id="task-456",
        )

        assert session.agent_url == "http://localhost:8000"
        assert session.context_id == "ctx-123"
        assert session.task_id == "task-456"

    def test_update_context_id(self):
        """Test updating context_id."""
        session = AgentSession(agent_url="http://localhost:8000")
        session.update(context_id="new-context")

        assert session.context_id == "new-context"
        assert session.task_id is None

    def test_update_task_id(self):
        """Test updating task_id."""
        session = AgentSession(agent_url="http://localhost:8000")
        session.update(task_id="new-task")

        assert session.context_id is None
        assert session.task_id == "new-task"

    def test_update_both_ids(self):
        """Test updating both context_id and task_id."""
        session = AgentSession(agent_url="http://localhost:8000")
        session.update(context_id="ctx-1", task_id="task-1")

        assert session.context_id == "ctx-1"
        assert session.task_id == "task-1"

    def test_update_preserves_existing_values_when_none_passed(self):
        """Test that update preserves existing values when None is passed."""
        session = AgentSession(
            agent_url="http://localhost:8000",
            context_id="existing-ctx",
            task_id="existing-task",
        )
        session.update()

        assert session.context_id == "existing-ctx"
        assert session.task_id == "existing-task"


class TestSessionStore:
    """Tests for SessionStore."""

    def test_get_creates_new_session(self):
        """Test that get creates a new session if none exists."""
        store = SessionStore()
        session = store.get("http://localhost:8000")

        assert session.agent_url == "http://localhost:8000"
        assert "http://localhost:8000" in store.sessions

    def test_get_returns_existing_session(self):
        """Test that get returns existing session."""
        store = SessionStore()
        store.sessions["http://localhost:8000"] = AgentSession(
            agent_url="http://localhost:8000",
            context_id="existing-ctx",
        )

        session = store.get("http://localhost:8000")
        assert session.context_id == "existing-ctx"

    def test_update_creates_and_updates_session(self):
        """Test that update creates and updates session."""
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            session = store.update(
                "http://localhost:8000",
                context_id="new-ctx",
                task_id="new-task",
            )

            assert session.context_id == "new-ctx"
            assert session.task_id == "new-task"

    def test_clear_specific_session(self):
        """Test clearing a specific session."""
        store = SessionStore()
        store.sessions["http://localhost:8000"] = AgentSession(
            agent_url="http://localhost:8000"
        )
        store.sessions["http://localhost:9000"] = AgentSession(
            agent_url="http://localhost:9000"
        )

        with tempfile.TemporaryDirectory() as temp_directory:
            store.session_directory = Path(temp_directory)
            store.clear("http://localhost:8000")

            assert "http://localhost:8000" not in store.sessions
            assert "http://localhost:9000" in store.sessions

    def test_clear_all_sessions(self):
        """Test clearing all sessions."""
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.sessions["http://localhost:8000"] = AgentSession(
                agent_url="http://localhost:8000"
            )
            store.sessions["http://localhost:9000"] = AgentSession(
                agent_url="http://localhost:9000"
            )

            store.clear()

            assert len(store.sessions) == 0

    def test_list_all_sessions(self):
        """Test listing all sessions."""
        store = SessionStore()
        store.sessions["http://localhost:8000"] = AgentSession(
            agent_url="http://localhost:8000"
        )
        store.sessions["http://localhost:9000"] = AgentSession(
            agent_url="http://localhost:9000"
        )

        all_sessions = store.list_all()
        assert len(all_sessions) == 2

    def test_save_and_load_sessions(self):
        """Test saving and loading sessions from disk."""
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.sessions["http://localhost:8000"] = AgentSession(
                agent_url="http://localhost:8000",
                context_id="ctx-123",
                task_id="task-456",
            )
            store.save()

            new_store = SessionStore(session_directory=Path(temp_directory))
            new_store.load()

            assert "http://localhost:8000" in new_store.sessions
            loaded_session = new_store.sessions["http://localhost:8000"]
            assert loaded_session.context_id == "ctx-123"
            assert loaded_session.task_id == "task-456"

    def test_save_and_load_sessions_with_keyring_credentials(self):
        """Test credential values are loaded from keyring-backed storage."""
        agent_url = "http://localhost:8000"

        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.sessions[agent_url] = AgentSession(
                agent_url=agent_url,
                credentials=create_bearer_auth("secret-token"),
            )

            with (
                patch.object(
                    SessionStore,
                    "_store_credential_in_keyring",
                    return_value=True,
                ),
                patch.object(
                    SessionStore,
                    "_get_credential_from_keyring",
                    return_value="secret-token",
                ),
            ):
                store.save()

                raw_data = json.loads(store.session_file_path.read_text())
                credentials_data = raw_data[agent_url]["credentials"]
                assert credentials_data["storage"] == CREDENTIAL_STORAGE_KEYRING
                assert "value" not in credentials_data

                new_store = SessionStore(session_directory=Path(temp_directory))
                new_store.load()

                loaded_credentials = new_store.get_credentials(agent_url)
                assert loaded_credentials is not None
                assert loaded_credentials.value == "secret-token"

    def test_load_legacy_credentials_prefers_keyring_secret(self):
        """Legacy plaintext credentials should defer to available keyring values."""
        agent_url = "http://localhost:8000"

        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store._ensure_directory_exists()
            store.session_file_path.write_text(
                json.dumps(
                    {
                        agent_url: {
                            "context_id": None,
                            "task_id": None,
                            "credentials": {
                                "auth_type": "bearer",
                                "value": "legacy-plaintext-token",
                                "header_name": None,
                            },
                        }
                    }
                )
            )

            with patch.object(
                SessionStore,
                "_get_credential_from_keyring",
                return_value="keyring-token",
            ):
                store.load()

            loaded_credentials = store.get_credentials(agent_url)
            assert loaded_credentials is not None
            assert loaded_credentials.value == "keyring-token"

    def test_save_falls_back_to_plaintext_credentials(self):
        """Test session file stores plaintext when keyring is unavailable."""
        agent_url = "http://localhost:8000"

        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.sessions[agent_url] = AgentSession(
                agent_url=agent_url,
                credentials=create_bearer_auth("secret-token"),
            )

            with patch.object(
                SessionStore,
                "_store_credential_in_keyring",
                return_value=False,
            ):
                store.save()

            raw_data = json.loads(store.session_file_path.read_text())
            credentials_data = raw_data[agent_url]["credentials"]
            assert credentials_data["storage"] == CREDENTIAL_STORAGE_PLAINTEXT
            assert credentials_data["value"] == "secret-token"

    def test_clear_credentials_deletes_keyring_entry(self):
        """Test clearing credentials removes any keyring secret."""
        agent_url = "http://localhost:8000"

        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.sessions[agent_url] = AgentSession(
                agent_url=agent_url,
                credentials=create_bearer_auth("secret-token"),
            )

            with patch.object(
                SessionStore,
                "_delete_credential_from_keyring",
            ) as mock_delete:
                store.clear_credentials(agent_url)

            mock_delete.assert_called_once_with(agent_url)

    @pytest.mark.skipif(
        sys.platform.startswith("win"),
        reason="Permission mode checks are POSIX-specific",
    )
    def test_save_hardens_session_storage_permissions(self):
        """Test save enforces restrictive directory and file permissions."""
        with tempfile.TemporaryDirectory() as temp_directory:
            session_directory = Path(temp_directory) / "handler-session"
            session_directory.mkdir(mode=0o755)

            store = SessionStore(session_directory=session_directory)
            store.sessions["http://localhost:8000"] = AgentSession(
                agent_url="http://localhost:8000",
                context_id="ctx-123",
            )
            store.save()

            directory_mode = stat.S_IMODE(session_directory.stat().st_mode)
            file_mode = stat.S_IMODE(store.session_file_path.stat().st_mode)

            assert directory_mode == 0o700
            assert file_mode == 0o600

    def test_load_nonexistent_file(self):
        """Test loading from nonexistent file does nothing."""
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.load()

            assert len(store.sessions) == 0

    def test_load_invalid_json(self):
        """Test loading invalid JSON file handles gracefully."""
        with tempfile.TemporaryDirectory() as temp_directory:
            session_file = Path(temp_directory) / "sessions.json"
            session_file.write_text("not valid json {{{")

            store = SessionStore(session_directory=Path(temp_directory))
            store.load()

            assert len(store.sessions) == 0
