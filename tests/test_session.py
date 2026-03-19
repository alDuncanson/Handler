"""Tests for the session state management module."""

import tempfile
from pathlib import Path

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.session import AgentSession, SessionStore


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

    def test_save_and_load_mtls_credentials(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            mtls_creds = AuthCredentials(
                auth_type=AuthType.MTLS,
                cert_path="/path/to/cert.pem",
                key_path="/path/to/key.pem",
                ca_cert_path="/path/to/ca.pem",
            )
            store.set_credentials("http://localhost:8000", mtls_creds)

            new_store = SessionStore(session_directory=Path(temp_directory))
            new_store.load()

            loaded_creds = new_store.get_credentials("http://localhost:8000")
            assert loaded_creds is not None
            assert loaded_creds.auth_type == AuthType.MTLS
            assert loaded_creds.cert_path == "/path/to/cert.pem"
            assert loaded_creds.key_path == "/path/to/key.pem"
            assert loaded_creds.ca_cert_path == "/path/to/ca.pem"

    def test_save_and_load_custom_headers(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            creds = AuthCredentials(
                auth_type=AuthType.BEARER,
                value="token",
                custom_headers={"x-user-id": "me@example.com", "x-org": "acme"},
            )
            store.set_credentials("http://localhost:8000", creds)

            new_store = SessionStore(session_directory=Path(temp_directory))
            new_store.load()

            loaded_creds = new_store.get_credentials("http://localhost:8000")
            assert loaded_creds is not None
            assert loaded_creds.custom_headers == {
                "x-user-id": "me@example.com",
                "x-org": "acme",
            }
