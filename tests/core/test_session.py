"""Tests for the session state management module."""

import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

from a2a_handler.session import AgentSession, SessionStore


class TestAgentSession:
    """Tests for AgentSession dataclass."""

    def test_create_session_with_url_only(self):
        session = AgentSession(agent_url="http://localhost:8000")

        assert session.agent_url == "http://localhost:8000"
        assert session.context_id is None
        assert session.task_id is None
        assert session.last_used_at is None

    def test_update_both_ids_and_last_used(self):
        session = AgentSession(agent_url="http://localhost:8000")
        session.update(
            context_id="ctx-1",
            task_id="task-1",
            last_used_at="2026-03-29T12:00:00+00:00",
        )

        assert session.context_id == "ctx-1"
        assert session.task_id == "task-1"
        assert session.last_used_at == "2026-03-29T12:00:00+00:00"


class TestSessionStore:
    """Tests for SessionStore."""

    def test_get_creates_new_session(self):
        store = SessionStore()
        session = store.get("http://localhost:8000")

        assert session.agent_url == "http://localhost:8000"
        assert "http://localhost:8000" in store.sessions

    def test_update_creates_and_updates_session(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            with patch(
                "a2a_handler.session._current_timestamp",
                return_value="2026-03-29T12:00:00+00:00",
            ):
                session = store.update(
                    "http://localhost:8000",
                    context_id="new-ctx",
                    task_id="new-task",
                )

            assert session.context_id == "new-ctx"
            assert session.task_id == "new-task"
            assert session.last_used_at == "2026-03-29T12:00:00+00:00"

    def test_set_conversation_replaces_saved_ids(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.sessions["http://localhost:8000"] = AgentSession(
                agent_url="http://localhost:8000",
                context_id="old-ctx",
                task_id="old-task",
            )

            with patch(
                "a2a_handler.session._current_timestamp",
                return_value="2026-03-29T12:00:00+00:00",
            ):
                session = store.set_conversation(
                    "http://localhost:8000",
                    context_id="new-ctx",
                    task_id=None,
                )

            assert session.context_id == "new-ctx"
            assert session.task_id is None
            assert session.last_used_at == "2026-03-29T12:00:00+00:00"

    def test_mark_recent_updates_last_used_without_changing_ids(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.sessions["http://localhost:8000"] = AgentSession(
                agent_url="http://localhost:8000",
                context_id="ctx-1",
                task_id="task-1",
            )

            with patch(
                "a2a_handler.session._current_timestamp",
                return_value="2026-03-29T12:00:00+00:00",
            ):
                session = store.mark_recent("http://localhost:8000")

            assert session.context_id == "ctx-1"
            assert session.task_id == "task-1"
            assert session.last_used_at == "2026-03-29T12:00:00+00:00"

    def test_clear_specific_session(self):
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

    def test_list_all_sessions_orders_by_recency(self):
        store = SessionStore()
        store.sessions["http://localhost:8000"] = AgentSession(
            agent_url="http://localhost:8000",
            last_used_at="2026-03-29T11:00:00+00:00",
        )
        store.sessions["http://localhost:9000"] = AgentSession(
            agent_url="http://localhost:9000",
            last_used_at="2026-03-29T12:00:00+00:00",
        )

        ordered = store.list_all()
        assert [session.agent_url for session in ordered] == [
            "http://localhost:9000",
            "http://localhost:8000",
        ]

    def test_recent_agent_urls_only_includes_touched_sessions(self):
        store = SessionStore()
        store.sessions["http://localhost:8000"] = AgentSession(
            agent_url="http://localhost:8000",
            last_used_at="2026-03-29T12:00:00+00:00",
        )
        store.sessions["http://localhost:9000"] = AgentSession(
            agent_url="http://localhost:9000",
        )

        assert store.recent_agent_urls() == ["http://localhost:8000"]

    def test_save_and_load_sessions(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.sessions["http://localhost:8000"] = AgentSession(
                agent_url="http://localhost:8000",
                context_id="ctx-123",
                task_id="task-456",
                last_used_at="2026-03-29T12:00:00+00:00",
            )
            store.save()

            new_store = SessionStore(session_directory=Path(temp_directory))
            new_store.load()

            loaded_session = new_store.sessions["http://localhost:8000"]
            assert loaded_session.context_id == "ctx-123"
            assert loaded_session.task_id == "task-456"
            assert loaded_session.last_used_at == "2026-03-29T12:00:00+00:00"

    def test_load_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.load()

            assert len(store.sessions) == 0

    def test_load_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            session_file = Path(temp_directory) / "sessions.json"
            session_file.write_text("not valid json {{{")

            store = SessionStore(session_directory=Path(temp_directory))
            store.load()

            assert len(store.sessions) == 0

    def test_save_sets_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.sessions["http://localhost:8000"] = AgentSession(
                agent_url="http://localhost:8000",
                context_id="ctx-1",
            )
            store.save()

            file_stat = os.stat(store.session_file_path)
            file_mode = stat.S_IMODE(file_stat.st_mode)
            assert file_mode == 0o600

    def test_save_is_atomic_no_temp_files_left(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            store = SessionStore(session_directory=Path(temp_directory))
            store.sessions["http://localhost:8000"] = AgentSession(
                agent_url="http://localhost:8000",
            )
            store.save()

            dir_contents = os.listdir(temp_directory)
            assert dir_contents == ["sessions.json"]
